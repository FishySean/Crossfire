"""HeartbeatJudge 用假时钟驱动，精确到每一拍；ThreadTicker 单独用真线程验一次。"""

import threading
import time
from collections.abc import Sequence

import pytest

from crossfire.adapters.system import ThreadTicker
from crossfire.application.events import Heartbeat
from crossfire.application.heartbeat import HeartbeatJudge, judge_with_heartbeat
from crossfire.application.use_cases import VerifyQuestion
from crossfire.domain import Claim, Judgment, Pair, Question
from tests.fakes import (
    CallLog,
    FakeClock,
    FakeExtractor,
    FakeFetcher,
    FakeJudge,
    FakePairer,
    InMemoryRunRepository,
    RecordingSink,
)
from tests.test_verify_question import QUESTION, URLS

INTERVAL = 5


class ClockAdvancingJudge(FakeJudge):
    def __init__(self, clock: FakeClock, seconds: float, error: Exception | None = None) -> None:
        super().__init__(CallLog(), trusted_url=URLS[0])
        self.clock = clock
        self.seconds = seconds
        self.error = error

    def judge(self, question: Question, claims: Sequence[Claim], pairs: Sequence[Pair]) -> Judgment:
        self.clock.advance(self.seconds)
        if self.error:
            raise self.error
        return super().judge(question, claims, pairs)


def test_twelve_seconds_of_judging_give_exactly_two_beats():
    clock, sink = FakeClock(), RecordingSink()
    inner = ClockAdvancingJudge(clock, seconds=12)
    judgment = HeartbeatJudge(inner, sink, clock, clock, INTERVAL).judge(QUESTION, [], [])

    assert sink.events == [Heartbeat("judge", 5.0), Heartbeat("judge", 10.0)]
    assert judgment.answer == "当前版本是 1.0"


def test_no_beats_after_the_judge_returns():
    clock, sink = FakeClock(), RecordingSink()
    HeartbeatJudge(ClockAdvancingJudge(clock, seconds=12), sink, clock, clock, INTERVAL).judge(QUESTION, [], [])
    clock.advance(60)

    assert len(sink.events) == 2
    assert clock.running_timers == 0


def test_beating_stops_even_when_the_judge_raises():
    clock, sink = FakeClock(), RecordingSink()
    inner = ClockAdvancingJudge(clock, seconds=7, error=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        HeartbeatJudge(inner, sink, clock, clock, INTERVAL).judge(QUESTION, [], [])
    clock.advance(60)

    assert sink.events == [Heartbeat("judge", 5.0)]


def test_without_a_sink_the_judge_is_not_wrapped_and_works_normally():
    clock = FakeClock()
    inner = ClockAdvancingJudge(clock, seconds=12)
    judge = judge_with_heartbeat(inner, None, clock, clock, INTERVAL)
    assert judge is inner

    log = CallLog()
    result = VerifyQuestion(
        FakeFetcher(), FakeExtractor(log), FakePairer(log), judge, InMemoryRunRepository(), RecordingSink(), clock
    ).execute(QUESTION).result
    assert result.judgment.answer == "当前版本是 1.0"
    assert result.steps["judge"].seconds == 12.0
    assert clock.running_timers == 0


def test_inside_the_use_case_beats_fall_between_judge_start_and_done():
    clock, sink = FakeClock(), RecordingSink()
    judge = judge_with_heartbeat(ClockAdvancingJudge(clock, seconds=12), sink, clock, clock, INTERVAL)
    log = CallLog()
    VerifyQuestion(FakeFetcher(), FakeExtractor(log), FakePairer(log), judge, InMemoryRunRepository(), sink, clock).execute(
        QUESTION
    )

    types = sink.types()
    assert types[types.index("judge_start") + 1 :] == ["heartbeat", "heartbeat", "done"]


def test_thread_ticker_ticks_until_stopped_and_never_after():
    ticks = []
    stop = ThreadTicker().every(0.005, lambda: ticks.append(threading.get_ident()))
    deadline = time.monotonic() + 2
    while len(ticks) < 3 and time.monotonic() < deadline:
        time.sleep(0.002)
    stop()
    count = len(ticks)
    time.sleep(0.03)

    assert count >= 3
    assert len(ticks) == count
    assert threading.get_ident() not in ticks
