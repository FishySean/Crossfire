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

    def to_dict(self) -> dict[str, Any]:
        return {**super().to_dict(), "judgment": self.judgment.to_dict()}


@dataclass(frozen=True)
class Error(_Event):
    type: ClassVar[str] = "error"
    step: str
    detail: str


type Event = Start | FetchDone | ClaimDone | PairStart | PairDone | JudgeStart | Heartbeat | Done | Error
