import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from typing import Any

from crossfire.adapters.anthropic.client import ClaudeClient, prompt_version
from crossfire.domain import Claim, Judgment, Pair, Provenance, Question, Relation, SourceRulingKind

# prompt 里出现的关系名一律从 Relation 填入，不手写字符串。
RELATION_NAMES = {
    "agree": Relation.AGREE.value,
    "contradict": Relation.CONTRADICT.value,
    "scope": Relation.SAME_QUESTION_DIFFERENT_SCOPE.value,
    "unrelated": Relation.UNRELATED.value,
}

JUDGE_PROMPT = """你在为一个事实查证引擎下最终结论。下面是一个问题、各来源提取出的主张，以及两两比对的结果。

今天的日期：{as_of}
{source_note}
问题：{question}

各来源的主张（JSON）：
{claims}

两两比对结果（JSON）：
{pairs}

关于你自己的知识，这几条优先于下面所有的判断原则：
（第 5b 步对照实验，2026-11-20：judge-python-2026-11 冻结修复前的 3 份输入，有这段和删掉这段都是 3/3 通过。
as_of 修好之后，靠「官方下载页 + 时效」就够了，这段没有改变结果。当初答错发生在模型不知道日期的时候；
这段只多几十个 token，留着当第二道防线。完整结果在 out/judge-ablation/。）
- 来源描述的事可能发生在你的训练数据之后。比你所知更新的版本号、日期、数字，本身不是来源出错的证据。
- 一手来源（primary）明确写出的事实，优先于你自己的知识。
- 不许以「超出已知范围」「与已知时间线不符」「版本号异常超前」之类的理由否定一手来源的明确陈述。
- 如果你认为某个一手来源有误，必须在 reasoning 里引用其他来源的原文（claims 里的 evidence）作为反证；
  你自己的知识不能当反证。
- 旧文章描述的是它发布时的情况。claims 里每个主张有两个日期字段：
  published_date（页面写明的发布/更新日）和 content_date（主张描述情况的时间点）。
  任一明显早于今天、又和较新的一手来源冲突时，视为过时，不能拿来印证或反驳一手来源。

判断原则，按优先级从高到低：
1. 来源层级：primary（一手源、官方文档）的权重高于 news（新闻报道），news 高于 aggregator（二手聚合站）
2. 时间：published_date 或 content_date 较新的主张优先，尤其当分歧属于「时间不同」时；
   两者都有时，页面发布日更能说明「这篇东西多新」，内容所述时间更能说明「它在讲哪一天的事」
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

source_rulings：本题 claims 里每一个来源 URL 恰好一条裁定（url 必须逐字相同）：
- trusted：采信、正确
- wrong：事实错误
- outdated：过时
- scope：口径/粒度不同，本身不算错
- neutral：未采信但也说不上错（例如无关、信息不足）
reason 用一两句中文或英文说明。不要漏掉任何来源 URL，也不要编造 claims 里没有的 URL。

请通过 record 工具返回结果。"""

# 只有 judge 需要长篇说理，它要复述每条冲突，输出长度随来源数增长，8 来源时 1000 会被截断。
# extract 和 pair 仍用 client.MAX_TOKENS=1000，小上限能防止模型啰嗦。judge 每次运行只调一次，成本可忽略。
JUDGE_MAX_TOKENS = 3000

_RULING_ENUM = [kind.value for kind in SourceRulingKind]

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
        "source_rulings": {
            "type": "array",
            "description": "每个来源一条裁定；url 必须来自本题 claims",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "ruling": {"type": "string", "enum": _RULING_ENUM},
                    "reason": {"type": "string"},
                },
                "required": ["url", "ruling", "reason"],
            },
        },
    },
    "required": ["answer", "confidence", "reasoning", "conflicts", "trusted_sources", "source_rulings"],
}

_NO_USAGE = {"input_tokens": 0, "output_tokens": 0, "requests": 0}


def _parse_for(question: Question):
    known = {source.url for source in question.sources}

    def _parse(data: dict[str, Any]) -> Judgment:
        judgment = Judgment.from_dict({**data, "usage": _NO_USAGE})
        judgment.validate_ruling_urls(known)
        return judgment

    return _parse


SOURCES_OVER_MEMORY_HEADING = "关于你自己的知识，"
PRINCIPLES_HEADING = "判断原则，按优先级"


def without_sources_over_memory(prompt: str = JUDGE_PROMPT) -> str:
    """对照实验用：去掉「关于你自己的知识」那一段，其余一字不改。"""
    start, end = prompt.index(SOURCES_OVER_MEMORY_HEADING), prompt.index(PRINCIPLES_HEADING)
    return prompt[:start] + prompt[end:]


class ClaudeVerdictJudge:
    def __init__(
        self,
        client: ClaudeClient,
        prompt: str = JUDGE_PROMPT,
        *,
        source_note: str = "",
    ) -> None:
        self._client = client
        self._prompt = prompt
        self._source_note = source_note

    @property
    def provenance(self) -> Provenance:
        return Provenance(model=self._client.model, prompt_version=prompt_version(self._prompt, JUDGE_SCHEMA))

    def judge(self, question: Question, claims: Sequence[Claim], pairs: Sequence[Pair], as_of: date) -> Judgment:
        note = self._source_note.strip()
        prompt = self._prompt.format(
            as_of=as_of.isoformat(),
            source_note=("\n" + note + "\n") if note else "",
            question=question.text,
            claims=json.dumps([claim.to_dict() for claim in claims], ensure_ascii=False, indent=2),
            pairs=json.dumps([pair.to_dict() for pair in pairs], ensure_ascii=False, indent=2),
            **RELATION_NAMES,
        )
        call = self._client.call(
            prompt, JUDGE_SCHEMA, "judge", _parse_for(question), max_tokens=JUDGE_MAX_TOKENS
        )
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
            source_rulings=None,
        )
