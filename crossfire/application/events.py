"""流水线推给前端的进度事件。

to_dict 的键名、键集合和顺序就是 SSE 契约，前端按它解析，tests/test_events.py 逐个锁住。
字段按 dataclass 的声明顺序输出，"type" 永远在最前，所以改字段顺序就是改契约。
"""

from dataclasses import dataclass, fields
from typing import Any, ClassVar

from crossfire.domain import Judgment


@dataclass(frozen=True)
class _Event:
    type: ClassVar[str]

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, **{field.name: getattr(self, field.name) for field in fields(self)}}


@dataclass(frozen=True)
class Start(_Event):
    type: ClassVar[str] = "start"
    question: str
    total_sources: int


@dataclass(frozen=True)
class FetchDone(_Event):
    type: ClassVar[str] = "fetch_done"
    url: str
    ok: bool
    chars: int
    index: int
    # 第 7 步新增：内容不可用时填原因（如 too_short）；抓取失败或成功时为 None。
    unusable_reason: str | None = None


@dataclass(frozen=True)
class ClaimDone(_Event):
    type: ClassVar[str] = "claim_done"
    url: str
    claim: str | None
    tier: str
    index: int
    # 第 7 步新增：提取失败时为 True；「没回答」时 claim 为 None 且 failed 为 False。
    failed: bool = False


@dataclass(frozen=True)
class PairStart(_Event):
    type: ClassVar[str] = "pair_start"
    total_pairs: int


@dataclass(frozen=True)
class PairDone(_Event):
    type: ClassVar[str] = "pair_done"
    a_url: str
    b_url: str
    relation: str | None
    nature: str | None
    index: int
    total: int
    # 第 7 步新增：NLI 比对器填写四类概率；Claude 为 None。
    scores: dict[str, float] | None = None


@dataclass(frozen=True)
class JudgeStart(_Event):
    type: ClassVar[str] = "judge_start"


@dataclass(frozen=True)
class Heartbeat(_Event):
    """只说明「还在跑、跑了多久」，不编造进度。"""

    type: ClassVar[str] = "heartbeat"
    step: str
    elapsed: float


@dataclass(frozen=True)
class Done(_Event):
    type: ClassVar[str] = "done"
    judgment: Judgment
    run_file: str
    elapsed: float
    # 第 9 步新增：仪表盘摘要；旧假事件可不填。
    summary: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "judgment": self.judgment.to_dict(),
            "summary": self.summary,
        }


@dataclass(frozen=True)
class Error(_Event):
    type: ClassVar[str] = "error"
    step: str
    detail: str


# ---- 第 7c 步：用户自提问 / 找来源（只新增，不改已有事件）----


@dataclass(frozen=True)
class SourceSearchStart(_Event):
    type: ClassVar[str] = "source_search_start"
    question: str
    question_id: str


@dataclass(frozen=True)
class SourceCandidate(_Event):
    type: ClassVar[str] = "source_candidate"
    url: str
    title: str
    tier: str


@dataclass(frozen=True)
class SourceFiltered(_Event):
    type: ClassVar[str] = "source_filtered"
    url: str
    reason: str
    detail: str


@dataclass(frozen=True)
class SourcesReady(_Event):
    type: ClassVar[str] = "sources_ready"
    count: int
    has_primary: bool
    urls: list[str]


@dataclass(frozen=True)
class SourcesInsufficient(_Event):
    type: ClassVar[str] = "sources_insufficient"
    kept: int
    found: int
    filtered: int
    detail: str


@dataclass(frozen=True)
class AskCostRejected(_Event):
    type: ClassVar[str] = "ask_cost_rejected"
    total_usd: float
    max_cost_usd: float
    # 第 8b 步新增：来源确定后的二次检查填真实来源数；运行前检查为 None。
    sources: int | None = None


type Event = (
    Start
    | FetchDone
    | ClaimDone
    | PairStart
    | PairDone
    | JudgeStart
    | Heartbeat
    | Done
    | Error
    | SourceSearchStart
    | SourceCandidate
    | SourceFiltered
    | SourcesReady
    | SourcesInsufficient
    | AskCostRejected
)
