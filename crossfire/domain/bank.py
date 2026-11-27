"""题库：自动生成的候选题、找来的来源、过滤原因。"""

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Self, cast

from crossfire.domain.models import Question, Source, Tier


class QuestionCategory(StrEnum):
    TIME_LAG = "time_lag"
    SCOPE = "scope"
    REPRINT_ERROR = "reprint_error"


# 题目里一旦出现这些，就会把分歧答案提前告诉 extract/pair，标签会被提示出来。
# 简称展开（如 LTS（长期支持））允许；长注释、vs、候选数字 or、转载/口径暗示一律拒绝。
_HINT_IN_PARENS = re.compile(
    r"[（(]([^）)]{0,200})[）)]",
)
_HINT_KEYWORDS = re.compile(
    r"vs\.?|口径|差异|转载|误写|抄错|错误写为|misprint|misattribut|figures?\s+differ|"
    r"differ\s+significantly|Note:|full-time|inland\s+water|联合国承认|非盟|实际控制|"
    r"sometimes\s+misprinted|omit\s+Rosalind|candidate|30\s+or\s+32",
    re.IGNORECASE,
)
_CANDIDATE_OR = re.compile(r"\b\d+\s+or\s+\d+\b", re.IGNORECASE)
_VS_OUTSIDE = re.compile(r"\bvs\.?\b", re.IGNORECASE)


def question_text_hint_reason(text: str) -> str | None:
    """若题目文字含答案提示/分歧暗示，返回原因；干净则返回 None。

    真实用户不会在括号里写「口径不同」或「转载误写 1911」。这类提示会泄漏进 extract/pair。
    """
    if _CANDIDATE_OR.search(text):
        return "候选答案 or"
    if _VS_OUTSIDE.search(text):
        return "vs 对照"
    if _HINT_KEYWORDS.search(text):
        return "暗示分歧或答案"
    for match in _HINT_IN_PARENS.finditer(text):
        inner = match.group(1).strip()
        if _HINT_KEYWORDS.search(inner):
            return "括号里的答案提示"
        # 超过约 12 个字的括号多半是出题注释，不是简称展开。
        if len(inner) > 12:
            return "括号注释"
    return None


class DropReason(StrEnum):
    """题目或来源被丢掉的原因，会写进 bank.yaml 和 bank-review.md。"""

    TOO_FEW_USABLE = "too_few_usable"
    NO_PRIMARY = "no_primary"
    UNUSABLE_PAGE = "unusable_page"
    FETCH_FAILED = "fetch_failed"
    KEYWORD_MISS = "keyword_miss"
    DUPLICATE_URL = "duplicate_url"
    # 余额不足等中断：不是「真的找不到来源」。续跑时要重做，不能跟 TOO_FEW_USABLE 混在一起。
    INTERRUPTED = "interrupted"


# 第 10 步：在保留现有题的前提下只扩 scope（+9），避免续跑时降级 time_lag / 再出 reprint。
CATEGORY_QUOTAS: dict[QuestionCategory, int] = {
    QuestionCategory.TIME_LAG: 9,
    QuestionCategory.SCOPE: 16,
    QuestionCategory.REPRINT_ERROR: 3,
}


@dataclass(frozen=True)
class CandidateSource:
    """SourceFinder 找到的一个候选网址。suggested_tier 是模型建议的层级，入库前可再调整。"""

    url: str
    title: str
    query: str
    suggested_tier: Tier

    def __post_init__(self) -> None:
        # 延迟导入，避免 bank ↔ models 循环依赖在类型检查期纠缠。
        from crossfire.domain.models import clean_source_url

        object.__setattr__(self, "url", clean_source_url(self.url))

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "query": self.query,
            "suggested_tier": self.suggested_tier.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            url=str(data["url"]),
            title=str(data["title"]),
            query=str(data["query"]),
            suggested_tier=Tier(str(data["suggested_tier"])),
        )


@dataclass(frozen=True)
class ProposedQuestion:
    """模型刚提出、还没找来源的一道题。"""

    id: str
    text: str
    category: QuestionCategory
    language: str
    keywords: tuple[str, ...]
    design_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "question": self.text,
            "category": self.category.value,
            "language": self.language,
            "keywords": list(self.keywords),
        }
        if self.design_note:
            payload["design_note"] = self.design_note
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        raw = data.get("keywords", [])
        if not isinstance(raw, list):
            raise TypeError("keywords 应为数组")
        keywords = tuple(str(item) for item in cast(list[object], raw))
        return cls(
            id=str(data["id"]),
            text=str(data.get("question") or data["text"]),
            category=QuestionCategory(str(data["category"])),
            language=str(data["language"]),
            keywords=keywords,
            design_note=str(data.get("design_note") or ""),
        )


@dataclass(frozen=True)
class RejectedSource:
    url: str
    reason: DropReason
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "reason": self.reason.value, "detail": self.detail}


@dataclass(frozen=True)
class KeptSource:
    source: Source
    title: str
    query: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.source.url,
            "tier": self.source.tier.value,
            "title": self.title,
            "found_by": self.query,
        }


@dataclass(frozen=True)
class BankQuestion:
    """通过过滤、可以进题库的一道题。"""

    id: str
    text: str
    category: QuestionCategory
    language: str
    generated_on: date
    keywords: tuple[str, ...]
    sources: tuple[KeptSource, ...]
    rejected: tuple[RejectedSource, ...]
    # 只给人看的出题意图（口径差异、常见转载错误等）。绝不进流水线 prompt。
    design_note: str = ""

    def to_pipeline_question(self) -> Question:
        """给 extract / pair / judge 用的题目：只有 id、正文、来源，不含 design_note。"""
        return Question(id=self.id, text=self.text, sources=tuple(item.source for item in self.sources))

    def to_yaml_dict(self) -> dict[str, Any]:
        """写入 questions/bank.yaml 的形态，sources 与 demo.yaml 兼容，额外字段跟在后面。"""
        payload: dict[str, Any] = {
            "id": self.id,
            "question": self.text,
            "category": self.category.value,
            "language": self.language,
            "generated_on": self.generated_on.isoformat(),
            "keywords": list(self.keywords),
            "sources": [item.to_dict() for item in self.sources],
            "rejected_sources": [item.to_dict() for item in self.rejected],
        }
        if self.design_note:
            payload["design_note"] = self.design_note
        return payload

    @classmethod
    def from_yaml_dict(cls, data: dict[str, Any]) -> Self:
        source_rows = cast(list[dict[str, Any]], data["sources"])
        sources = tuple(
            KeptSource(
                source=Source(url=str(item["url"]), tier=Tier(str(item["tier"]))),
                title=str(item.get("title") or item["url"]),
                query=str(item.get("found_by") or item.get("query") or ""),
            )
            for item in source_rows
        )
        rejected_rows = cast(list[dict[str, Any]], data.get("rejected_sources") or [])
        rejected = tuple(
            RejectedSource(url=str(item["url"]), reason=DropReason(str(item["reason"])), detail=str(item["detail"]))
            for item in rejected_rows
        )
        raw_keywords = data.get("keywords", [])
        if not isinstance(raw_keywords, list):
            keywords: tuple[str, ...] = ()
        else:
            keywords = tuple(str(item) for item in cast(list[object], raw_keywords))
        text = str(data["question"])
        reason = question_text_hint_reason(text)
        if reason is not None:
            raise ValueError(f"{data.get('id')}: 题目含答案提示（{reason}）：{text}")
        return cls(
            id=str(data["id"]),
            text=text,
            category=QuestionCategory(str(data["category"])),
            language=str(data["language"]),
            generated_on=date.fromisoformat(str(data["generated_on"])),
            keywords=keywords,
            sources=sources,
            rejected=rejected,
            design_note=str(data.get("design_note") or ""),
        )


@dataclass(frozen=True)
class DroppedQuestion:
    proposed: ProposedQuestion
    reason: DropReason
    detail: str
    rejected: tuple[RejectedSource, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.proposed.to_dict(),
            "drop_reason": self.reason.value,
            "drop_detail": self.detail,
            "rejected_sources": [item.to_dict() for item in self.rejected],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        rejected_rows = cast(list[dict[str, Any]], data.get("rejected_sources") or [])
        rejected = tuple(
            RejectedSource(url=str(item["url"]), reason=DropReason(str(item["reason"])), detail=str(item["detail"]))
            for item in rejected_rows
        )
        return cls(
            proposed=ProposedQuestion.from_dict(data),
            reason=DropReason(str(data["drop_reason"])),
            detail=str(data["drop_detail"]),
            rejected=rejected,
        )
