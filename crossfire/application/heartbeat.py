from collections.abc import Sequence
from datetime import date

from crossfire.application.events import Heartbeat
from crossfire.application.ports import Clock, EventSink, Ticker, VerdictJudge
from crossfire.domain import Claim, Judgment, Pair, Provenance, Question


class HeartbeatJudge:
    """给 VerdictJudge 套一层：判决进行期间每隔 interval 秒推一次 heartbeat 事件。

    judge 是一次阻塞调用，中间没有任何可报告的进度，实测能跑到 27 秒。
    心跳只说明「还在跑、跑了多久」，不编造进度，让前端的超时计时器有东西可重置。
    """

    def __init__(
        self,
        inner: VerdictJudge,
        events: EventSink,
        clock: Clock,
        ticker: Ticker,
        interval: float,
    ) -> None:
        self._inner = inner
        self._events = events
        self._clock = clock
        self._ticker = ticker
        self._interval = interval

    @property
    def provenance(self) -> Provenance:
        return self._inner.provenance

    def judge(self, question: Question, claims: Sequence[Claim], pairs: Sequence[Pair], as_of: date | None) -> Judgment:
        started = self._clock.monotonic()

        def beat() -> None:
            self._events.emit(Heartbeat(step="judge", elapsed=round(self._clock.monotonic() - started, 2)))

        stop = self._ticker.every(self._interval, beat)
        try:
            return self._inner.judge(question, claims, pairs, as_of)
        finally:
            stop()


def judge_with_heartbeat(
    judge: VerdictJudge,
    events: EventSink | None,
    clock: Clock,
    ticker: Ticker,
    interval: float,
) -> VerdictJudge:
    """没人收事件就不包装，连计时线程都不开。这个判断只在组装依赖时做一次，业务代码里没有。"""
    if events is None:
        return judge
    return HeartbeatJudge(judge, events, clock, ticker, interval)
