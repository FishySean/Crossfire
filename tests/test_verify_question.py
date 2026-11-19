"""VerifyQuestion 用例：全部依赖都是 tests/fakes.py 里的假实现，时钟也是假的，不碰文件、线程、网络。"""

from collections.abc import Sequence
from dataclasses import replace

import pytest

from crossfire.application.events import Done, Error
from crossfire.application.use_cases import VerifyQuestion
from crossfire.domain import Claim, Judgment, Mode, Pair, Question, Usage
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
from tests.test_pipeline_contract import EVENT_FIELDS

SOURCES = [
    {"url": "https://a.example/", "tier": "primary"},
    {"url": "https://b.example/", "tier": "primary"},
    {"url": "https://c.example/", "tier": "news"},
    {"url": "https://d.example/", "tier": "aggregator"},
]
QUESTION = Question.from_dict({"id": "use-case", "question": "当前版本是多少？", "sources": SOURCES})
URLS = [s["url"] for s in SOURCES]


class SlowJudge(FakeJudge):
    """判决期间让假时钟走 seconds 秒。"""

    def __init__(self, log: CallLog, clock: FakeClock, seconds: float) -> None:
        super().__init__(log, trusted_url=URLS[0])
        self.clock = clock
        self.seconds = seconds

    def judge(self, question: Question, claims: Sequence[Claim], pairs: Sequence[Pair]) -> Judgment:
        self.clock.advance(self.seconds)
        return super().judge(question, claims, pairs)


@pytest.fixture
def build():
    def install(fetcher=None, pairer=None, judge=None, clock=None):
        log = CallLog()
        clock = clock or FakeClock()
        parts = {
            "fetcher": fetcher or FakeFetcher(),
            "extractor": FakeExtractor(log),
            "pairer": pairer or FakePairer(log),
            "judge": judge or FakeJudge(log, trusted_url=URLS[0]),
            "runs": InMemoryRunRepository(),
            "events": RecordingSink(),
            "clock": clock,
        }
        return VerifyQuestion(**parts), parts

    return install


def test_stages_run_in_order_and_every_event_has_the_contract_shape(build):
    use_case, parts = build()
    use_case.execute(QUESTION)

    sink = parts["events"]
    assert sink.types() == (
        ["start"] + ["fetch_done"] * 4 + ["claim_done"] * 4 + ["pair_start"] + ["pair_done"] * 6 + ["judge_start", "done"]
    )
    for event in sink.events:
        assert set(event.to_dict()) == EVENT_FIELDS[event.type]


def test_returns_exactly_what_it_saved_and_done_carries_the_location(build):
    use_case, parts = build()
    saved = use_case.execute(QUESTION)
    result = saved.result

    assert parts["runs"].saved == [result]
    # 第 4 步有意修改：新增 location 断言。原因：决定 1，execute 返回 SavedRun(result, location)
    assert saved.location == "memory://1"
    done = parts["events"].events[-1]
    assert isinstance(done, Done)
    assert done.run_file == "memory://1"
    assert done.judgment == result.judgment
    assert done.elapsed == result.elapsed_seconds


@pytest.mark.parametrize("mode", list(Mode))
def test_mode_comes_from_the_fetcher(build, mode):
    use_case, _ = build(fetcher=FakeFetcher(mode=mode))
    assert use_case.execute(QUESTION).result.mode is mode


def test_timings_come_from_the_injected_clock(build):
    clock = FakeClock()
    use_case, _ = build(judge=SlowJudge(CallLog(), clock, seconds=3.0), clock=clock)
    result = use_case.execute(QUESTION).result

    assert result.started_at == FakeClock.START
    assert result.steps["judge"].seconds == 3.0
    assert result.steps["fetch"].seconds == 0.0
    assert result.elapsed_seconds == 3.0


def test_failed_pages_are_not_extracted_and_claim_index_stays_the_source_index(build):
    use_case, parts = build(fetcher=FakeFetcher(failing_urls={URLS[1]}))
    result = use_case.execute(QUESTION).result

    assert [claim.source_url for claim in result.claims] == [URLS[0], URLS[2], URLS[3]]
    claim_done = [e.to_dict() for e in parts["events"].events if e.type == "claim_done"]
    assert [e["index"] for e in claim_done] == [0, 2, 3]
    errors = [e for e in parts["events"].events if isinstance(e, Error)]
    assert [(e.step, e.detail) for e in errors] == [("fetch", f"假的抓取失败 {URLS[1]}")]


def test_step_stats(build):
    use_case, _ = build()
    steps = use_case.execute(QUESTION).result.steps

    assert {name: stats.calls for name, stats in steps.items()} == {"fetch": 4, "extract": 4, "pair": 6, "judge": 1}
    assert steps["fetch"].input_tokens is None
    assert (steps["pair"].input_tokens, steps["pair"].output_tokens) == (60, 12)


EIGHT = Question.from_dict(
    {
        "id": "eight",
        "question": "当前版本是多少？",
        "sources": [{"url": f"https://s{i}.example/", "tier": "news"} for i in range(8)],
    }
)


def test_eight_sources_three_fetch_failures_give_exactly_three_fetch_failures(build):
    failing = {"https://s1.example/", "https://s4.example/", "https://s6.example/"}
    use_case, _ = build(fetcher=FakeFetcher(failing_urls=failing))
    result = use_case.execute(EIGHT).result

    fetch_failures = [f for f in result.failures if f.step == "fetch"]
    assert len(fetch_failures) == 3
    assert [f.detail for f in fetch_failures] == [f"假的抓取失败 {url}" for url in sorted(failing)]
    assert all(f.raw is None for f in fetch_failures)
    assert len(result.failures) == 3
    assert result.to_dict()["failures"] == [f.to_dict() for f in fetch_failures]


def test_all_pages_failing_is_still_loud(build):
    use_case, _ = build(fetcher=FakeFetcher(failing_urls=set(URLS)))
    result = use_case.execute(QUESTION).result

    assert result.claims == () and result.pairs == ()
    assert [f.step for f in result.failures] == ["fetch"] * 4


class RetryingExtractor(FakeExtractor):
    """第一个来源的提取重试过一次：两次请求。"""

    def extract(self, question, page):
        claim = super().extract(question, page)
        if page.url == URLS[0]:
            return replace(claim, usage=Usage(20, 4, requests=2))
        return claim


def test_model_requests_counts_retried_requests(build):
    _, parts = build()
    result = VerifyQuestion(**{**parts, "extractor": RetryingExtractor(CallLog())}).execute(QUESTION).result

    # 第 4 步有意修改：claude_calls → model_requests。原因：决定 3，代码里改名，JSON 键名不变
    assert result.model_requests == 4 + 6 + 1 + 1
    assert result.steps["extract"].calls == 4
    assert result.steps["extract"].requests == 5


# ---- 第 4 步：接上页面可用性 ----


def test_unusable_pages_are_not_extracted_and_become_usability_failures(build):
    use_case, parts = build(fetcher=FakeFetcher(unusable_urls={URLS[2]}))
    result = use_case.execute(QUESTION).result

    assert [claim.source_url for claim in result.claims] == [URLS[0], URLS[1], URLS[3]]
    assert [(f.step, f.detail, f.raw) for f in result.failures] == [("usability", "too_short", None)]
    assert result.pages_fetched == 4 and result.pages_failed == 0
    assert [page.usable for page in result.pages] == [True, True, False, True]


def test_unusable_page_card_reaches_its_final_state(build):
    """前端收到 ok=false 的 fetch_done 就把卡片画成终态，不再等 claim_done；error 进失败横幅。"""
    use_case, parts = build(fetcher=FakeFetcher(unusable_urls={URLS[2]}))
    use_case.execute(QUESTION)

    events = [e.to_dict() for e in parts["events"].events]
    fetch_done = {e["index"]: e for e in events if e["type"] == "fetch_done"}
    assert fetch_done[2]["ok"] is False
    assert fetch_done[2]["chars"] > 0
    assert [e["index"] for e in events if e["type"] == "claim_done"] == [0, 1, 3]
    errors = [e for e in events if e["type"] == "error"]
    assert errors == [{"type": "error", "step": "usability", "detail": "too_short"}]
    assert events.index(errors[0]) == events.index(fetch_done[2]) + 1


def test_fetch_error_detail_is_always_a_string(build):
    """决定 4：error 事件的 detail 和 Failure.detail 用同一句兜底文字，不会是 None。"""
    use_case, parts = build(fetcher=FakeFetcher(errorless_urls={URLS[1]}))
    result = use_case.execute(QUESTION).result

    [error] = [e for e in parts["events"].events if isinstance(e, Error)]
    [failure] = result.failures
    assert error.detail == failure.detail == "抓取失败，没有错误信息"
