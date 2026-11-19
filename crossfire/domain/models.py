"""Crossfire 的实体。只依赖标准库。

to_dict/from_dict 放在实体上，是因为字段名和 JSON 键名并不一一对应（Claim.text 写出去叫
"claim"，Pair.a_url 叫 "a"），而这些键名是前端和 out/runs/*.json 依赖的对外契约。映射和字段写在
同一处，改字段时才不会漏改键名。转成字符串、读写文件是外层的事，这里不碰 json。

from_dict 读的是本项目自己写出的结构，键缺失或枚举值不认识都直接抛错，不做兜底。
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, NewType, Self

from crossfire.domain.relations import Relation

# 来源在 Question.sources 里的下标。fetch_done、claim_done 的 index 都必须是它，前端按它定位卡片槽。
# 曾经有人用「已提取主张的个数」当下标，有页面抓取失败时整排卡片错位。
# 只应该从 Question.index_of 拿到它。注意 NewType 只对类型检查器生效，运行时它就是 int。
SourceIndex = NewType("SourceIndex", int)


class Tier(StrEnum):
    PRIMARY = "primary"
    NEWS = "news"
    AGGREGATOR = "aggregator"


class Mode(StrEnum):
    LIVE = "live"
    CACHED = "cached"


class SourceType(StrEnum):
    """值与 extract.EXTRACT_SCHEMA 的 source_type enum 逐字相同。"""

    OFFICIAL_DOCUMENTATION = "official_documentation"
    NEWS_ARTICLE = "news_article"
    ENCYCLOPEDIA = "encyclopedia"
    BLOG = "blog"
    FORUM = "forum"
    OTHER = "other"


def _optional[E: StrEnum](enum: type[E], value: str | None) -> E | None:
    return None if value is None else enum(value)


class UnknownSourceError(KeyError):
    """URL 不在这个问题的来源列表里。"""


@dataclass(frozen=True)
class Source:
    url: str
    tier: Tier

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "tier": self.tier.value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(url=data["url"], tier=Tier(data["tier"]))


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    sources: tuple[Source, ...]

    def __post_init__(self) -> None:
        # URL 是来源的身份：主张、比对、tier 查找全靠它。重复的 URL 会让 index_of 无法回答。
        urls = [source.url for source in self.sources]
        duplicates = sorted({url for url in urls if urls.count(url) > 1})
        if duplicates:
            raise ValueError(f"问题 {self.id} 的来源 URL 重复：{duplicates}")

    def index_of(self, url: str) -> SourceIndex:
        for index, source in enumerate(self.sources):
            if source.url == url:
                return SourceIndex(index)
        raise UnknownSourceError(url)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "question": self.text, "sources": [s.to_dict() for s in self.sources]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            id=data["id"],
            text=data["question"],
            sources=tuple(Source.from_dict(s) for s in data["sources"]),
        )


@dataclass(frozen=True)
class Usage:
    """一个步骤的 token 用量，包含该步骤内部所有重试的累计。"""

    input_tokens: int
    output_tokens: int

    def to_dict(self) -> dict[str, Any]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(input_tokens=data["input_tokens"], output_tokens=data["output_tokens"])


@dataclass(frozen=True)
class Failure:
    """一次 LLM 步骤在重试后仍然失败。raw 是最后一次的原始响应，供人排查。"""

    step: str
    detail: str
    raw: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"step": self.step, "detail": self.detail, "raw": self.raw}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(step=data["step"], detail=data["detail"], raw=data["raw"])


def _string_list(data: dict[str, Any], key: str) -> tuple[str, ...]:
    # 模型偶尔把数组整个编码成一个 JSON 字符串返回，直接 tuple() 会把它静默拆成单个字符。
    value = data[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} 应为数组，实际是 {type(value).__name__}：{str(value)[:80]}")
    return tuple(value)


def _failure_from(data: dict[str, Any]) -> Failure | None:
    return Failure.from_dict(data["failure"]) if "failure" in data else None


def _with_failure(body: dict[str, Any], failure: Failure | None) -> dict[str, Any]:
    # 没失败时不写 failure 键，而不是写 null：现有结果文件和前端都按「键是否存在」判断。
    if failure is not None:
        body["failure"] = failure.to_dict()
    return body


@dataclass(frozen=True)
class Link:
    text: str
    url: str


@dataclass(frozen=True)
class Page:
    """一次抓取的结果。

    ok 只表示「抓取这一步没有报错」，不代表 HTTP 2xx，也不代表内容可用。
    内容可不可用由 domain.usability 判断。
    """

    url: str
    ok: bool
    title: str | None = None
    markdown: str | None = None
    links: tuple[Link, ...] = ()
    error: str | None = None
    status_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "ok": self.ok,
            "title": self.title,
            "markdown": self.markdown,
            "links": [{"text": link.text, "url": link.url} for link in self.links],
            "error": self.error,
            "status_code": self.status_code,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        # 只有 url 和 ok 必填：抓取失败、缓存缺失、手写的测试页面都会缺其余字段。
        # usable / unusable_reason 这类派生键直接忽略，需要时用 usability 重新算。
        return cls(
            url=data["url"],
            ok=data["ok"],
            title=data.get("title"),
            markdown=data.get("markdown"),
            links=tuple(Link(text=link["text"], url=link["url"]) for link in data.get("links") or ()),
            error=data.get("error"),
            status_code=data.get("status_code"),
        )


@dataclass(frozen=True)
class Claim:
    """一个来源针对问题给出的主张。

    text 为 None 表示该页面没有回答这个问题——或者提取失败了，此时 failure 非空。
    提取失败时 source_type、confidence 等字段也都是 None，所以它们全都是可选的。
    """

    source_url: str
    tier: Tier
    text: str | None
    evidence: str | None
    source_type: SourceType | None
    published_date: str | None
    confidence: float | None
    usage: Usage
    failure: Failure | None = None

    @property
    def answered(self) -> bool:
        return self.text is not None

    def to_dict(self) -> dict[str, Any]:
        return _with_failure(
            {
                "url": self.source_url,
                "tier": self.tier.value,
                "claim": self.text,
                "evidence": self.evidence,
                "source_type": None if self.source_type is None else self.source_type.value,
                "confidence": self.confidence,
                "published_date": self.published_date,
                "usage": self.usage.to_dict(),
            },
            self.failure,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            source_url=data["url"],
            tier=Tier(data["tier"]),
            text=data["claim"],
            evidence=data["evidence"],
            source_type=_optional(SourceType, data["source_type"]),
            published_date=data["published_date"],
            confidence=data["confidence"],
            usage=Usage.from_dict(data["usage"]),
            failure=_failure_from(data),
        )


@dataclass(frozen=True)
class Pair:
    """两个已回答主张之间的比对。比对失败时 relation 和 nature 为 None，failure 非空。"""

    a_url: str
    b_url: str
    relation: Relation | None
    nature: str | None
    usage: Usage
    failure: Failure | None = None

    def to_dict(self) -> dict[str, Any]:
        return _with_failure(
            {
                "a": self.a_url,
                "b": self.b_url,
                "relation": None if self.relation is None else self.relation.value,
                "nature": self.nature,
                "usage": self.usage.to_dict(),
            },
            self.failure,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            a_url=data["a"],
            b_url=data["b"],
            relation=_optional(Relation, data["relation"]),
            nature=data["nature"],
            usage=Usage.from_dict(data["usage"]),
            failure=_failure_from(data),
        )


@dataclass(frozen=True)
class Judgment:
    """最终结论。

    conflicts 是模型写的自由文本，没有指回具体哪一对 Pair。
    trusted_sources 是模型给出的 URL 字符串，不保证都在问题的来源列表里，所以没有用 SourceIndex。
    """

    answer: str | None
    confidence: float | None
    reasoning: str | None
    conflicts: tuple[str, ...]
    trusted_sources: tuple[str, ...]
    usage: Usage
    failure: Failure | None = None

    def to_dict(self) -> dict[str, Any]:
        return _with_failure(
            {
                "answer": self.answer,
                "confidence": self.confidence,
                "reasoning": self.reasoning,
                "conflicts": list(self.conflicts),
                "trusted_sources": list(self.trusted_sources),
                "usage": self.usage.to_dict(),
            },
            self.failure,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            answer=data["answer"],
            confidence=data["confidence"],
            reasoning=data["reasoning"],
            conflicts=_string_list(data, "conflicts"),
            trusted_sources=_string_list(data, "trusted_sources"),
            usage=Usage.from_dict(data["usage"]),
            failure=_failure_from(data),
        )


@dataclass(frozen=True)
class StepStats:
    """一个步骤的耗时和用量。

    calls 是这一步产出的记录条数，不是实际发出的 API 请求数（重试不计入）。
    fetch 步骤不调 LLM，input_tokens / output_tokens 为 None，写出时省略这两个键。
    """

    calls: int
    seconds: float
    input_tokens: int | None = None
    output_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.input_tokens is None:
            return {"calls": self.calls, "seconds": self.seconds}
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "seconds": self.seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            calls=data["calls"],
            seconds=data["seconds"],
            input_tokens=data.get("input_tokens"),
            output_tokens=data.get("output_tokens"),
        )


@dataclass(frozen=True)
class RunResult:
    """跑完一次的完整结果，对应 out/runs/*.json 的一个文件。

    pages_fetched、failures、token 总数等都由已有字段推出，做成属性而不是字段，
    避免存一份可能对不上的副本。claude_calls 和 failures 照搬了当前的算法，
    两者都有已登记的问题（见 notes/refactor-backlog.md），修的时候改这里一处。
    """

    question: Question
    mode: Mode
    started_at: datetime
    elapsed_seconds: float
    steps: dict[str, StepStats]
    pages: tuple[Page, ...]
    claims: tuple[Claim, ...]
    pairs: tuple[Pair, ...]
    judgment: Judgment

    @property
    def pages_fetched(self) -> int:
        return sum(1 for page in self.pages if page.ok)

    @property
    def pages_failed(self) -> int:
        return sum(1 for page in self.pages if not page.ok)

    @property
    def claude_calls(self) -> int:
        return len(self.claims) + len(self.pairs) + 1

    @property
    def failures(self) -> tuple[Failure, ...]:
        records = [*self.claims, *self.pairs, self.judgment]
        return tuple(record.failure for record in records if record.failure is not None)

    @property
    def total_input_tokens(self) -> int:
        return sum(step.input_tokens or 0 for step in self.steps.values())

    @property
    def total_output_tokens(self) -> int:
        return sum(step.output_tokens or 0 for step in self.steps.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question.id,
            "question": self.question.text,
            "mode": self.mode.value,
            "started_at": self.started_at.isoformat(),
            "elapsed_seconds": self.elapsed_seconds,
            "sources": [source.to_dict() for source in self.question.sources],
            "pages_fetched": self.pages_fetched,
            "pages_failed": self.pages_failed,
            "claude_calls": self.claude_calls,
            "failures": [failure.to_dict() for failure in self.failures],
            "steps": {name: step.to_dict() for name, step in self.steps.items()},
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "pages": [page.to_dict() for page in self.pages],
            "claims": [claim.to_dict() for claim in self.claims],
            "pairs": [pair.to_dict() for pair in self.pairs],
            "judgment": self.judgment.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            question=Question(
                id=data["question_id"],
                text=data["question"],
                sources=tuple(Source.from_dict(s) for s in data["sources"]),
            ),
            mode=Mode(data["mode"]),
            started_at=datetime.fromisoformat(data["started_at"]),
            elapsed_seconds=data["elapsed_seconds"],
            steps={name: StepStats.from_dict(step) for name, step in data["steps"].items()},
            pages=tuple(Page.from_dict(page) for page in data["pages"]),
            claims=tuple(Claim.from_dict(claim) for claim in data["claims"]),
            pairs=tuple(Pair.from_dict(pair) for pair in data["pairs"]),
            judgment=Judgment.from_dict(data["judgment"]),
        )
