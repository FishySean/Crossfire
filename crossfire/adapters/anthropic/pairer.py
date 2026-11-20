import sys
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import replace
from typing import Any

from crossfire.adapters.anthropic.client import ClaudeCallError, ClaudeClient, prompt_version
from crossfire.application.ports import OnPair
from crossfire.domain import Claim, Failure, Pair, Provenance, Question, Relation, Usage

DEFAULT_PAIR_CONCURRENCY = 6

# prompt 里出现的关系名一律从 Relation 填入，不手写字符串。
RELATION_NAMES = {
    "agree": Relation.AGREE.value,
    "contradict": Relation.CONTRADICT.value,
    "scope": Relation.SAME_QUESTION_DIFFERENT_SCOPE.value,
    "unrelated": Relation.UNRELATED.value,
}

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

relation 只能四选一，判定标准如下：

{contradict} —— 两个说法测量或定义的是同一个东西，但不可能同时为真，必有一方错误或已过时。
  典型情形：数字不同、日期不同、归属不同，或一方明确肯定而另一方明确否定。

{scope} —— 两个说法各自为真，但基于不同的定义或统计范围，不可直接比较。
  判定这一类必须同时满足三个条件：
  1. 两个说法给出的答案确实不同（如果答案相同，那是 {agree}）；
  2. 差异的成因是可以指名道姓的口径差异——你必须能在 nature 里说出 A 用的是哪个范围、B 用的是哪个范围；
  3. 在同一个当前时刻，两者依然各自成立，不存在谁过时、谁算错。
  调和这种分歧的办法是「说清你问的是哪个口径」，而不是「判定谁错了」。

{agree} —— 两个说法可以同时为真，且指向同一个结论。
  重要：当一方只是另一方的更粗粒度表述、或两者详略不同时，属于 {agree} 而不是 {contradict}。
  「无法互相印证」「粒度不够细」「没有提到具体数字」都不构成矛盾。

{unrelated} —— 两者在谈不同的事，既不能互相印证也不能互相反驳。

判定示例，请严格照此标准：
- 「最新版本是 3.14.7」 vs 「3.14 处于 bugfix 阶段」 → {agree}。
  3.14.7 就是 3.14 系列中的一个补丁版本，两句话同时成立，只是详略不同。这是粒度差异，不是矛盾。
- 「最新版本是 3.14.7」 vs 「最新版本是 3.13」 → {contradict}。
  同一时刻最新版只能有一个，两者不可能同时为真。
- 「太阳系有 8 颗行星」 vs 「冥王星是矮行星不是行星」 → {agree}。
  后者正是前者的成因，两者互相印证。
- 「太阳系有 8 颗行星」 vs 「太阳系有 9 颗行星」 → {contradict}。
- 「最新版本是 3.14.7」 vs 「Python 是一门解释型语言」 → {unrelated}。
- 「东京人口 1424 万」 vs 「东京人口 3700 万」 → {scope}。
  前者是东京都这一行政区划，后者是含周边数县的大东京都市圈。两个数字当下同时成立，
  谁都没算错，差别在于「东京」指的是哪一片地方。
- 「该公司有 5 万名员工」 vs 「该公司有 8 万名员工」 → {scope}，
  前提是能看出一方只算全职、另一方含合同工。如果看不出口径差异在哪，就不是这一类。
- 「珠峰高 8844.43 米」 vs 「珠峰高 8848.86 米」 → {scope}，
  前者是岩面高度，后者是雪盖顶部高度，量的是两个不同的东西。

与 {contradict} 的边界，这是最容易搞错的地方，请逐条对照：

- 时间差**不是**口径差。如果两个说法在各自发布时间点上都曾成立，但因为事实本身变了而
  不能同时描述「当前」，那是 {contradict}，不是 {scope}。
  例：「Active LTS 是 v22」（2024 年文章） vs 「Active LTS 是 v24」（2026 年文章） → {contradict}。
  两者量的是同一个东西（当前 Active LTS 版本），只是前者过时了，必须判 {contradict}
  并在 nature 里说明哪一方已过时。
- 说不出口径就不是口径差。如果你只能说「两者可能统计方法不同」而指不出具体是哪两个范围，
  那说明你在给矛盾找借口，应判 {contradict}。
- 答案相同就不是这一类。口径不同但结论一致的，判 {agree}。
- 一方根本没回答这个问题的，判 {unrelated}，不要判 {scope}。

nature 字段要求：
- 先归类到 数字不同 / 时间不同 / 定义口径不同 / 粒度不同 / 完全无关 之一，再用一句话说明差异在哪。
- 如果你判定 {contradict}，必须在 nature 里明确说出「这两句话为什么不能同时为真」。
  如果你说不出这一点，那就不是 {contradict}，请改判 {agree} 或 {unrelated}。
- 如果你判定 {scope}，必须在 nature 里分别写出 A 和 B 各自采用的口径。
  写不出来的就不是这一类。

请通过 record 工具返回结果。"""

PAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "relation": {
            "type": "string",
            "enum": [relation.value for relation in Relation],
            "description": "两个主张的关系",
        },
        "nature": {
            "type": "string",
            "description": "先归类（数字不同/时间不同/定义口径不同/粒度不同/完全无关），"
            f"再一句话说明差异。判 {Relation.CONTRADICT.value} 时必须说明两句话为何不能同时为真；"
            f"判 {Relation.SAME_QUESTION_DIFFERENT_SCOPE.value} 时必须分别写出 A 和 B 各自采用的口径",
        },
    },
    "required": ["relation", "nature"],
}

_NO_USAGE = {"input_tokens": 0, "output_tokens": 0, "requests": 0}


class ClaudeClaimPairer:
    """Claude 一次只能判一对，所以整批在内部用线程池并发发请求，并发数受 concurrency 限制。"""

    def __init__(self, client: ClaudeClient, concurrency: int = DEFAULT_PAIR_CONCURRENCY) -> None:
        self._client = client
        self._concurrency = concurrency

    @property
    def provenance(self) -> Provenance:
        return Provenance(model=self._client.model, prompt_version=prompt_version(PAIR_PROMPT, PAIR_SCHEMA))

    def pair_all(
        self,
        question: Question,
        claim_pairs: Sequence[tuple[Claim, Claim]],
        on_pair: OnPair | None = None,
    ) -> list[Pair]:
        total = len(claim_pairs)
        results: list[Pair | None] = [None] * total
        executor = ThreadPoolExecutor(max_workers=self._concurrency)
        try:
            futures: dict[Future[Pair], int] = {
                executor.submit(self._compare, question, a, b): index for index, (a, b) in enumerate(claim_pairs)
            }
            # 回调在调用方线程里按完成顺序触发，事件推送方不用处理多线程。
            for future in as_completed(futures):
                index = futures[future]
                pair = future.result()
                results[index] = pair
                if on_pair:
                    on_pair(index, total, pair)
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
        return [pair for pair in results if pair is not None]

    def _compare(self, question: Question, a: Claim, b: Claim) -> Pair:
        prompt = PAIR_PROMPT.format(
            question=question.text,
            a_url=a.source_url,
            a_tier=a.tier.value,
            a_date=a.published_date,
            a_claim=a.text,
            a_evidence=a.evidence,
            b_url=b.source_url,
            b_tier=b.tier.value,
            b_date=b.published_date,
            b_claim=b.text,
            b_evidence=b.evidence,
            **RELATION_NAMES,
        )

        def parse(data: dict[str, Any]) -> Pair:
            return Pair.from_dict({**data, "a": a.source_url, "b": b.source_url, "usage": _NO_USAGE})

        # 端口约定 pair_all 不抛异常，见 ClaimPairer.pair_all。网络重试用尽、鉴权失败都落到这里。
        try:
            call = self._client.call(prompt, PAIR_SCHEMA, "pair", parse)
        except ClaudeCallError as e:
            return self._failed(a, b, str(e), e.usage)
        except Exception as e:
            # 不是 API 抛的，不知道请求有没有发出去，请求数记成未知，不编一个数。
            return self._failed(a, b, f"{type(e).__name__}: {e}", Usage(0, 0, None))
        if call.value is not None:
            return replace(call.value, usage=call.usage)
        return Pair(
            a_url=a.source_url,
            b_url=b.source_url,
            relation=None,
            nature=None,
            usage=call.usage,
            failure=call.failure,
        )

    def _failed(self, a: Claim, b: Claim, detail: str, usage: Usage) -> Pair:
        print(f"❌ [llm] pair 调用抛出异常，该对记为失败：{detail}", file=sys.stderr)
        return Pair(
            a_url=a.source_url,
            b_url=b.source_url,
            relation=None,
            nature=None,
            usage=usage,
            failure=Failure(step="pair", detail=detail, raw=None),
        )
