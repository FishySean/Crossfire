import itertools
import json
import os

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1000

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

严格按下面的字段返回一个 JSON 对象：
- relation: 只能是 agree、contradict、unrelated 三者之一。agree 表示两者对该问题的回答实质一致；
  contradict 表示两者对该问题给出了不能同时成立的回答；unrelated 表示两者在谈不同的事，无法构成对立
- nature: 一句话说明差异到底在哪，请明确归类到下面某一种：数字不同 / 时间不同 / 定义口径不同 / 完全无关。
  如果 relation 是 agree，就说明两者一致在什么点上

注意区分"真矛盾"和"口径差异"：两个来源统计范围、定义或时间点不同而导致数字不同，
属于定义口径不同或时间不同，不要一概判成 contradict 之外，也不要把它描述成某一方出错。

只输出这个 JSON 对象本身。不要 markdown 代码围栏，不要任何前言或解释。"""

JUDGE_PROMPT = """你在为一个事实查证引擎下最终结论。下面是一个问题、各来源提取出的主张，以及两两比对的结果。

问题：{question}

各来源的主张（JSON）：
{claims}

两两比对结果（JSON）：
{pairs}

判断原则，按优先级从高到低：
1. 来源层级：primary（一手源、官方文档）的权重高于 news（新闻报道），news 高于 aggregator（二手聚合站）
2. 时间：published_date 较新的主张优先，尤其当分歧属于"时间不同"时
3. 区分矛盾性质：如果分歧来自统计口径、定义范围或时间点不同，必须明确指出"这不是谁错了，而是口径/时间不同"，
   不要强行裁定某一方错误

严格按下面的字段返回一个 JSON 对象：
- answer: 对该问题的最终回答，一到两句话
- confidence: 0 到 1 之间的数字，表示你对这个回答的置信度。来源之间冲突越多、越缺少一手源，置信度应越低
- reasoning: 你如何得到这个结论，说明你采信了哪些来源、为什么，以及如何处理了分歧
- conflicts: 字符串数组，逐条描述发现的实质分歧及其性质。没有分歧则返回空数组
- trusted_sources: 字符串数组，你实际采信的来源 URL，按可信度从高到低排列

只输出这个 JSON 对象本身。不要 markdown 代码围栏，不要任何前言或解释。"""


def pair_claims(question: str, claims: list[dict]) -> list[dict]:
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    answered = [c for c in claims if c.get("claim")]
    pairs = []

    for a, b in itertools.combinations(answered, 2):
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
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        pair = {
            "a": a["url"],
            "b": b["url"],
            "relation": None,
            "nature": None,
            "usage": {
                "input_tokens": message.usage.input_tokens,
                "output_tokens": message.usage.output_tokens,
            },
        }
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            pair["parse_error"] = str(e)
            pair["raw"] = raw
            pairs.append(pair)
            continue

        pair["relation"] = parsed.get("relation")
        pair["nature"] = parsed.get("nature")
        pairs.append(pair)

    return pairs


def judge(question: str, claims: list[dict], pairs: list[dict]) -> dict:
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    prompt = JUDGE_PROMPT.format(
        question=question,
        claims=json.dumps(claims, ensure_ascii=False, indent=2),
        pairs=json.dumps(pairs, ensure_ascii=False, indent=2),
    )
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()

    result = {
        "answer": None,
        "confidence": None,
        "reasoning": None,
        "conflicts": [],
        "trusted_sources": [],
    }
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        result["parse_error"] = str(e)
        result["raw"] = raw
    else:
        for key in list(result):
            if key in parsed:
                result[key] = parsed[key]

    result["usage"] = {
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
    }
    return result
