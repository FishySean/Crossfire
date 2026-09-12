import asyncio
import itertools
import json

from crossfire.llm import call_structured

DEFAULT_PAIR_CONCURRENCY = 6

PAIR_PROMPT = """你在为一个事实查证引擎比对两个来源对同一个问题的主张。

问题：{question}

来源 A
URL: {a_url}
层级: {a_tier}
发布日期: {a_date}
主张: {a_claim}
原文依据: {a_evidence}

来源 B
URL: {b_url}
层级: {b_tier}
发布日期: {b_date}
主张: {b_claim}
原文依据: {b_evidence}

relation 只能三选一，判定标准如下：

contradict —— 两个说法不可能同时为真。
  典型情形：数字不同、日期不同、归属不同，或一方明确肯定而另一方明确否定。

agree —— 两个说法可以同时为真，且指向同一个结论。
  重要：当一方只是另一方的更粗粒度表述、或两者详略不同时，属于 agree 而不是 contradict。
  「无法互相印证」「粒度不够细」「没有提到具体数字」都不构成矛盾。

unrelated —— 两者在谈不同的事，既不能互相印证也不能互相反驳。

判定示例，请严格照此标准：
- 「最新版本是 3.14.7」 vs 「3.14 处于 bugfix 阶段」 → agree。
  3.14.7 就是 3.14 系列中的一个补丁版本，两句话同时成立，只是详略不同。这是粒度差异，不是矛盾。
- 「最新版本是 3.14.7」 vs 「最新版本是 3.13」 → contradict。
  同一时刻最新版只能有一个，两者不可能同时为真。
- 「太阳系有 8 颗行星」 vs 「冥王星是矮行星不是行星」 → agree。
  后者正是前者的成因，两者互相印证。
- 「太阳系有 8 颗行星」 vs 「太阳系有 9 颗行星」 → contradict。
- 「最新版本是 3.14.7」 vs 「Python 是一门解释型语言」 → unrelated。

时效性差异的处理：如果两个说法在各自的发布时间点上都曾成立，但对「当前」这个问题
不能同时为真，仍判 contradict，并在 nature 里说明这是时效性差异、哪一方已过时。

nature 字段要求：
- 先归类到 数字不同 / 时间不同 / 定义口径不同 / 粒度不同 / 完全无关 之一，再用一句话说明差异在哪。
- 如果你判定 contradict，必须在 nature 里明确说出「这两句话为什么不能同时为真」。
  如果你说不出这一点，那就不是 contradict，请改判 agree 或 unrelated。

请通过 record 工具返回结果。"""

PAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "relation": {
            "type": "string",
            "enum": ["agree", "contradict", "unrelated"],
            "description": "两个主张的关系",
        },
        "nature": {
            "type": "string",
            "description": "先归类（数字不同/时间不同/定义口径不同/粒度不同/完全无关），"
            "再一句话说明差异。判 contradict 时必须说明两句话为何不能同时为真",
        },
    },
    "required": ["relation", "nature"],
}

JUDGE_PROMPT = """你在为一个事实查证引擎下最终结论。下面是一个问题、各来源提取出的主张，以及两两比对的结果。

问题：{question}

各来源的主张（JSON）：
{claims}

两两比对结果（JSON）：
{pairs}

判断原则，按优先级从高到低：
1. 来源层级：primary（一手源、官方文档）的权重高于 news（新闻报道），news 高于 aggregator（二手聚合站）
2. 时间：published_date 较新的主张优先，尤其当分歧属于「时间不同」时
3. 区分矛盾性质：如果分歧来自统计口径、定义范围、粒度详略或时间点不同，必须明确指出
   「这不是谁错了，而是口径/粒度/时间不同」，不要强行裁定某一方错误

来源之间冲突越多、越缺少一手源，confidence 应越低。

请通过 record 工具返回结果。"""

# 只有 judge 需要长篇说理，它要复述每条冲突，输出长度随来源数增长，8 来源时 1000 会被截断。
# extract 和 pair 仍用 llm.MAX_TOKENS=1000，小上限能防止模型啰嗦。judge 每次运行只调一次，成本可忽略。
JUDGE_MAX_TOKENS = 3000

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "对该问题的最终回答，一到两句话"},
        "confidence": {"type": "number", "description": "0 到 1 的置信度"},
        "reasoning": {
            "type": "string",
            "description": "如何得到该结论：采信了哪些来源、为什么、如何处理分歧",
        },
        "conflicts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "逐条描述发现的实质分歧及其性质，没有分歧则为空数组",
        },
        "trusted_sources": {
            "type": "array",
            "items": {"type": "string"},
            "description": "实际采信的来源 URL，按可信度从高到低排列",
        },
    },
    "required": ["answer", "confidence", "reasoning", "conflicts", "trusted_sources"],
}


async def pair_claims(
    question: str,
    claims: list[dict],
    concurrency: int = DEFAULT_PAIR_CONCURRENCY,
    on_pair=None,
) -> list[dict]:
    answered = [c for c in claims if c.get("claim")]
    combos = list(itertools.combinations(answered, 2))
    semaphore = asyncio.Semaphore(concurrency)
    pairs: list[dict | None] = [None] * len(combos)

    async def compare(index: int, a: dict, b: dict) -> None:
        prompt = PAIR_PROMPT.format(
            question=question,
            a_url=a["url"],
            a_tier=a.get("tier"),
            a_date=a.get("published_date"),
            a_claim=a.get("claim"),
            a_evidence=a.get("evidence"),
            b_url=b["url"],
            b_tier=b.get("tier"),
            b_date=b.get("published_date"),
            b_claim=b.get("claim"),
            b_evidence=b.get("evidence"),
        )
        async with semaphore:
            data = await asyncio.to_thread(call_structured, prompt, PAIR_SCHEMA, "pair")

        pair = {
            "a": a["url"],
            "b": b["url"],
            "relation": data.get("relation"),
            "nature": data.get("nature"),
            "usage": data["_usage"],
        }
        if "_failure" in data:
            pair["failure"] = data["_failure"]
        pairs[index] = pair
        if on_pair:
            on_pair(index, len(combos), pair)

    await asyncio.gather(*(compare(i, a, b) for i, (a, b) in enumerate(combos)))
    return [p for p in pairs if p is not None]


def judge(question: str, claims: list[dict], pairs: list[dict]) -> dict:
    prompt = JUDGE_PROMPT.format(
        question=question,
        claims=json.dumps(claims, ensure_ascii=False, indent=2),
        pairs=json.dumps(pairs, ensure_ascii=False, indent=2),
    )
    data = call_structured(prompt, JUDGE_SCHEMA, "judge", max_tokens=JUDGE_MAX_TOKENS)

    result = {
        "answer": data.get("answer"),
        "confidence": data.get("confidence"),
        "reasoning": data.get("reasoning"),
        "conflicts": data.get("conflicts") or [],
        "trusted_sources": data.get("trusted_sources") or [],
        "usage": data["_usage"],
    }
    if "_failure" in data:
        result["failure"] = data["_failure"]
    return result
