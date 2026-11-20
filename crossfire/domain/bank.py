"""题库：自动生成的候选题、找来的来源、过滤原因。"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Self, cast

from crossfire.domain.models import Source, Tier


class QuestionCategory(StrEnum):
    TIME_LAG = "time_lag"
    SCOPE = "scope"
    REPRINT_ERROR = "reprint_error"


class DropReason(StrEnum):
    """题目或来源被丢掉的原因，会写进 bank.yaml 和 bank-review.md。"""

    TOO_FEW_USABLE = "too_few_usable"
    UNUSABLE_PAGE = "unusable_page"
    FETCH_FAILED = "fetch_failed"
    KEYWORD_MISS = "keyword_miss"
    DUPLICATE_URL = "duplicate_url"


@dataclass(frozen=True)
class CandidateSource:
    """SourceFinder 找到的一个候选网址。suggested_tier 是模型建议的层级，入库前可再调整。"""

    url: str
    title: str
    query: str
    suggested_tier: Tier

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.text,
            "category": self.category.value,
            "language": self.language,
            "keywords": list(self.keywords),
        }

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

    def to_yaml_dict(self) -> dict[str, Any]:
        """写入 questions/bank.yaml 的形态，sources 与 demo.yaml 兼容，额外字段跟在后面。"""
        return {
            "id": self.id,
            "question": self.text,
            "category": self.category.value,
            "language": self.language,
            "generated_on": self.generated_on.isoformat(),
            "keywords": list(self.keywords),
            "sources": [item.to_dict() for item in self.sources],
            "rejected_sources": [item.to_dict() for item in self.rejected],
        }


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
