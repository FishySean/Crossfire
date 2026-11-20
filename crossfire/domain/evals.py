"""评测集：事先知道标准答案的题。每次改 prompt 前后各跑一遍，看答对了几道。

标准答案来自冻结的网页快照，不来自任何一次模型输出：评测集要独立于被测对象。
判分看 judgment.answer 的文字，有的题还看 reasoning。规则全是确定的正则和数字区间，
同一个答案永远得到同一个结果，不用另一个模型来打分。每条规则都带 why，写明为什么这么判。

题分两类。full 题跑完整条流水线，页面读冻结快照。judge 题只测判决这一步：输入是事先存好的
claims 和 pairs，每份输入只调一次 judge，用来专门制造判决必须处理的局面（比如旧文章说的「目前」
和比模型知识更新的一手来源冲突），不受提取那一步好坏的影响。
"""

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Protocol, Self

from crossfire.domain.models import Claim, Pair


class Rule(Protocol):
    @property
    def why(self) -> str: ...

    def check(self, answer: str) -> str | None:
        """通过返回 None，没通过返回原因。"""
        ...


@dataclass(frozen=True)
class LeadsWith:
    """答案里必须出现 expected，而且在任何一个 competitor 之前出现。

    答案的第一句就是结论，后面才是背景。只要求「出现过」的话，「最新版是 3.13.x，3.15.2 存疑」
    这种答错的回答也会因为提到了 3.15.2 而通过。
    """

    expected: str
    competitors: tuple[str, ...]
    why: str

    def check(self, answer: str) -> str | None:
        hit = re.search(self.expected, answer)
        if hit is None:
            return f"答案里没有标准答案（{self.expected}）"
        for pattern in self.competitors:
            other = re.search(pattern, answer)
            if other is not None and other.start() < hit.start():
                return f"先出现的是「{other.group()}」，排在标准答案「{hit.group()}」前面"
        return None


@dataclass(frozen=True)
class Forbids:
    pattern: str
    why: str

    def check(self, answer: str) -> str | None:
        hit = re.search(self.pattern, answer)
        return None if hit is None else f"出现了不该有的「{hit.group()}」"


@dataclass(frozen=True)
class Figure:
    value: float
    text: str
    start: int


# 只认带单位的数（万、million）和千分位写法的整数。不带单位的普通整数多半是年份、日期，不算。
_FIGURE = re.compile(r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(万|million|百万)?")
_UNITS = {"万": 10_000, "million": 1_000_000, "百万": 1_000_000}
_SENTENCE_END = re.compile(r"[。；;！!？?\n①②③④⑤]")


def figures(text: str) -> list[Figure]:
    found: list[Figure] = []
    for match in _FIGURE.finditer(text):
        number, unit = match.group(1), match.group(2)
        if unit is None and "," not in number:
            continue
        value = float(number.replace(",", "")) * (_UNITS[unit] if unit else 1)
        found.append(Figure(value=value, text=match.group(0).strip(), start=match.start()))
    return found


def sentence_around(text: str, position: int) -> str:
    """position 所在的那一句：前后各找到最近的句末标点或编号为止。逗号不断句。"""
    start = max((m.end() for m in _SENTENCE_END.finditer(text, 0, position)), default=0)
    end_match = _SENTENCE_END.search(text, position)
    return text[start : end_match.start() if end_match else len(text)]


@dataclass(frozen=True)
class FigureInRange:
    low: int
    high: int
    why: str

    def check(self, answer: str) -> str | None:
        if any(self.low <= figure.value <= self.high for figure in figures(answer)):
            return None
        return f"没有落在 {self.low:,} 到 {self.high:,} 之间的数字"


@dataclass(frozen=True)
class FigureNeedsContext:
    """落在 low 到 high 之间的数字，所在的那一句必须出现 context。"""

    low: int
    high: int
    context: str
    why: str

    def check(self, answer: str) -> str | None:
        for figure in figures(answer):
            if self.low <= figure.value <= self.high and not re.search(self.context, sentence_around(answer, figure.start)):
                return f"「{figure.text}」所在的句子没有说明口径（要有 {self.context}）"
        return None


def sentences(text: str) -> list[str]:
    """按句末标点和编号切句，逗号不断句。与 sentence_around 同一套标点。"""
    return [part for part in _SENTENCE_END.split(text) if part.strip()]


@dataclass(frozen=True)
class ForbidsInSentence:
    """同一句里同时命中 all_of 的每一个模式、又不含 unless 里的任何一个，就算没通过。

    用来抓「拿模型自己的知识否定来源」：同一句里既提到自己的知识（知识截止、训练数据……），
    又说来源可疑。只禁其中一类词会误杀：「3.15.2 晚于我的训练数据，但这不是来源出错的证据」
    是照规则办事的正确推理，所以带否定说法的句子用 unless 放过。
    """

    all_of: tuple[str, ...]
    unless: tuple[str, ...]
    why: str

    def check(self, answer: str) -> str | None:
        for sentence in sentences(answer):
            if all(re.search(p, sentence) for p in self.all_of) and not any(re.search(p, sentence) for p in self.unless):
                return f"这句拿自己的知识否定来源：「{sentence.strip()[:80]}」"
        return None


RULE_KINDS: dict[str, type] = {
    "leads_with": LeadsWith,
    "forbids": Forbids,
    "figure_in_range": FigureInRange,
    "figure_needs_context": FigureNeedsContext,
    "forbids_in_sentence": ForbidsInSentence,
}


def rule_from_dict(data: dict[str, Any]) -> Rule:
    fields = dict(data)
    kind = fields.pop("kind")
    if kind not in RULE_KINDS:
        raise ValueError(f"不认识的判分规则 {kind}，可选：{'、'.join(RULE_KINDS)}")
    if not str(fields.get("why") or "").strip():
        raise ValueError(f"判分规则 {kind} 缺 why：每条规则都要写明为什么这么判")
    for pattern_key in ("expected", "pattern", "context"):
        if pattern_key in fields:
            re.compile(fields[pattern_key])
    for list_key in ("competitors", "all_of", "unless"):
        if list_key in fields:
            fields[list_key] = tuple(fields[list_key])
            for pattern in fields[list_key]:
                re.compile(pattern)
    return RULE_KINDS[kind](**fields)


@dataclass(frozen=True)
class Grade:
    passed: bool
    reasons: tuple[str, ...]

    def failing(self, reason: str) -> "Grade":
        return Grade(passed=False, reasons=(*self.reasons, reason))


@dataclass(frozen=True)
class Evidence:
    """标准答案的依据：url 那一页的冻结快照里逐字出现的原文。"""

    url: str
    quote: str


class CaseKind(StrEnum):
    FULL = "full"
    JUDGE = "judge"


@dataclass(frozen=True)
class JudgeInput:
    """judge 题的一份冻结输入：某次真实运行产出的 claims 和 pairs，原样存下。source 写明取自哪次运行。"""

    source: str
    claims: tuple[Claim, ...]
    pairs: tuple[Pair, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            source=str(data["source"]),
            claims=tuple(Claim.from_dict(claim) for claim in data["claims"]),
            pairs=tuple(Pair.from_dict(pair) for pair in data["pairs"]),
        )


@dataclass(frozen=True)
class EvalCase:
    """snapshot 是标准答案依据所在的冻结页面目录名，默认就是 id。judge 题不读页面，
    但标准答案照样要站在页面原文上，所以指向它所用 claims 的那份快照。"""

    id: str
    question_id: str
    as_of: date
    gold_answer: str
    evidence: tuple[Evidence, ...]
    rules: tuple[Rule, ...]
    repeats: int
    kind: CaseKind = CaseKind.FULL
    snapshot: str = ""
    reasoning_rules: tuple[Rule, ...] = ()

    def grade(self, answer: str | None, reasoning: str | None = None) -> Grade:
        if not answer:
            return Grade(passed=False, reasons=("没有给出答案",))
        reasons = [reason for rule in self.rules if (reason := rule.check(answer)) is not None]
        if self.reasoning_rules:
            if not reasoning:
                reasons.append("没有给出推理")
            else:
                reasons += [f"推理里：{reason}" for rule in self.reasoning_rules if (reason := rule.check(reasoning)) is not None]
        return Grade(passed=not reasons, reasons=tuple(reasons))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        as_of = data["as_of"]
        if not isinstance(as_of, date):
            as_of = date.fromisoformat(str(as_of))
        evidence = tuple(Evidence(url=item["url"], quote=item["quote"]) for item in data["evidence"])
        rules = tuple(rule_from_dict(rule) for rule in data["rules"])
        if not evidence or not rules:
            raise ValueError(f"评测题 {data['id']} 必须有依据和判分规则")
        repeats = data.get("repeats", 1)
        if not isinstance(repeats, int) or repeats < 1:
            raise ValueError(f"评测题 {data['id']} 的 repeats 必须是正整数")
        return cls(
            id=data["id"],
            question_id=data["question_id"],
            as_of=as_of,
            gold_answer=data["gold_answer"],
            evidence=evidence,
            rules=rules,
            repeats=repeats,
            kind=CaseKind(data.get("kind", CaseKind.FULL.value)),
            snapshot=data.get("snapshot") or data["id"],
            reasoning_rules=tuple(rule_from_dict(rule) for rule in data.get("reasoning_rules", [])),
        )
