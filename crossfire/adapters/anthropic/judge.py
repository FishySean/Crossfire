import json
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from crossfire.adapters.anthropic.client import ClaudeClient
from crossfire.domain import Claim, Judgment, Pair, Question, Relation

# prompt 里出现的关系名一律从 Relation 填入，不手写字符串。
RELATION_NAMES = {
    "agree": Relation.AGREE.value,
    "contradict": Relation.CONTRADICT.value,
    "scope": Relation.SAME_QUESTION_DIFFERENT_SCOPE.value,
    "unrelated": Relation.UNRELATED.value,
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

比对结果里的 relation 含义：
- {contradict} 是真分歧，必有一方错误或已过时，你要裁定该信哪一方
- {scope} 表示两者各自为真、只是口径不同。这不是真分歧，
  不要为它扣置信度，也不要裁定谁错。正确处理方式是在 answer 里按口径分别作答，
  并在 conflicts 里说明这是口径差异而非事实冲突
- {agree} 和 {unrelated} 不需要裁定

confidence 应反映 {contradict} 的多少和一手源的有无；
{scope} 再多也不该把置信度压低。

请通过 record 工具返回结果。"""

# 只有 judge 需要长篇说理，它要复述每条冲突，输出长度随来源数增长，8 来源时 1000 会被截断。
# extract 和 pair 仍用 client.MAX_TOKENS=1000，小上限能防止模型啰嗦。judge 每次运行只调一次，成本可忽略。
JUDGE_MAX_TOKENS = 3000

JUDGE_SCHEMA: dict[str, Any] = {
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

_NO_USAGE = {"input_tokens": 0, "output_tokens": 0}


def _parse(data: dict[str, Any]) -> Judgment:
    return Judgment.from_dict({**data, "usage": _NO_USAGE})


class ClaudeVerdictJudge:
    def __init__(self, client: ClaudeClient) -> None:
        self._client = client

    def judge(self, question: Question, claims: Sequence[Claim], pairs: Sequence[Pair]) -> Judgment:
        prompt = JUDGE_PROMPT.format(
            question=question.text,
            claims=json.dumps([claim.to_dict() for claim in claims], ensure_ascii=False, indent=2),
            pairs=json.dumps([pair.to_dict() for pair in pairs], ensure_ascii=False, indent=2),
            **RELATION_NAMES,
        )
        call = self._client.call(prompt, JUDGE_SCHEMA, "judge", _parse, max_tokens=JUDGE_MAX_TOKENS)
        if call.value is not None:
            return replace(call.value, usage=call.usage)
        return Judgment(
            answer=None,
            confidence=None,
            reasoning=None,
            conflicts=(),
            trusted_sources=(),
            usage=call.usage,
            failure=call.failure,
        )
