"""端口的假实现，直接注入，不需要 monkeypatch。

数据与第 0 步那套 monkeypatch 假数据一致：每个来源都说「当前版本是 1.0」，比对一律 agree。
"""

import threading
import time
from collections.abc import Callable, Collection, Sequence
from datetime import UTC, datetime, timedelta

from crossfire.application.events import Event
from crossfire.application.ports import (
    ClaimExtractor,
    ClaimPairer,
    Clock,
    EventSink,
    OnPage,
    OnPair,
    PageFetcher,
    RunRepository,
    Ticker,
    VerdictJudge,
)
from crossfire.domain import (
    Claim,
    Failure,
    Judgment,
    Mode,
    Page,
    Pair,
    Question,
    Relation,
    RunResult,
    SourceIndex,
    SourceType,
    Usage,
)

USAGE = Usage(input_tokens=10, output_tokens=2, requests=1)
PROSE = "This sentence is ordinary article prose that is long enough to count here.\n" * 20
FETCHED_AT = datetime(2026, 9, 12, 21, 16, 0, tzinfo=UTC)


class CallLog:
    """按调用顺序记下各端口被调用的步骤名。pairer 可能被并发调用，所以加锁。"""

    def __init__(self) -> None:
        self.steps: list[str] = []
        self._lock = threading.Lock()

    def record(self, step: str) -> None:
        with self._lock:
            self.steps.append(step)


class FakeFetcher:
    def __init__(
        self,
        failing_urls: Collection[str] = (),
        unusable_urls: Collection[str] = (),
        mode: Mode = Mode.LIVE,
        errorless_urls: Collection[str] = (),
        fetched_at: datetime | None = FETCHED_AT,
    ) -> None:
        self.mode = mode
        self.failing_urls = failing_urls
        self.unusable_urls = unusable_urls
        self.errorless_urls = errorless_urls
        self.fetched_at = fetched_at
        self.fetched: list[str] = []

    def fetch_all(self, urls: Sequence[str], on_page: OnPage | None = None) -> list[Page]:
        pages: list[Page] = []
        for index, url in enumerate(urls):
            self.fetched.append(url)
            if url in self.failing_urls:
                page = Page(url=url, ok=False, error=f"假的抓取失败 {url}", status_code=503, fetched_at=self.fetched_at)
            elif url in self.errorless_urls:
                page = Page(url=url, ok=False, fetched_at=self.fetched_at)
            else:
                # 不可用页面：正文太短，usability 会判成 too_short。
                markdown = f"正文 {url}" if url in self.unusable_urls else f"正文 {url}\n{PROSE}"
                page = Page(
                    url=url,
                    ok=True,
                    title=f"标题 {url}",
                    markdown=markdown,
                    status_code=200,
                    fetched_at=self.fetched_at,
                )
            if on_page:
                on_page(SourceIndex(index), page)
            pages.append(page)
        return pages


class FakeExtractor:
    def __init__(self, log: CallLog, texts: dict[str, str] | None = None) -> None:
        self.log = log
        self.texts = texts or {}

    def extract(self, question: Question, page: Page) -> Claim:
        self.log.record("extract")
        return Claim(
            source_url=page.url,
            tier=question.source_of(page.url).tier,
            text=self.texts.get(page.url, f"{page.url} 说当前版本是 1.0"),
            evidence="version 1.0",
            source_type=SourceType.OFFICIAL_DOCUMENTATION,
            published_date=None,
            confidence=0.9,
            usage=USAGE,
        )


class FakePairer:
    """一律 agree；两个 URL 都在 failing_pair_urls 里的那一对返回失败。"""

    def __init__(self, log: CallLog, failing_pair_urls: Collection[str] | None = None) -> None:
        self.log = log
        self.failing_pair_urls = failing_pair_urls

    def pair_all(
        self,
        question: Question,
        claim_pairs: Sequence[tuple[Claim, Claim]],
        on_pair: OnPair | None = None,
    ) -> list[Pair]:
        pairs: list[Pair] = []
        for index, (a, b) in enumerate(claim_pairs):
            self.log.record("pair")
            if self.failing_pair_urls and {a.source_url, b.source_url} <= set(self.failing_pair_urls):
                failure = Failure(step="pair", detail="假的 pair 失败", raw="[]")
                pair = Pair(a.source_url, b.source_url, relation=None, nature=None, usage=USAGE, failure=failure)
            else:
                pair = Pair(a.source_url, b.source_url, Relation.AGREE, "粒度不同——测试数据", USAGE)
            if on_pair:
                on_pair(index, len(claim_pairs), pair)
            pairs.append(pair)
        return pairs


class EqualityPairer:
    """只看两条主张的文字是否相同：相同判 agree，不同判 contradict。

    它是接入自训 NLI 模型的演练：一个与 Claude 毫无关系的比对实现，注入进去就能跑完整条流水线。
    """

    def __init__(self) -> None:
        self.batches: list[int] = []

    def pair_all(
        self,
        question: Question,
        claim_pairs: Sequence[tuple[Claim, Claim]],
        on_pair: OnPair | None = None,
    ) -> list[Pair]:
        self.batches.append(len(claim_pairs))
        pairs = [
            Pair(
                a.source_url,
                b.source_url,
                Relation.AGREE if a.text == b.text else Relation.CONTRADICT,
                "文字相同" if a.text == b.text else "文字不同",
                Usage(0, 0, 0),
            )
            for a, b in claim_pairs
        ]
        for index, pair in enumerate(pairs):
            if on_pair:
                on_pair(index, len(pairs), pair)
        return pairs


class FakeJudge:
    def __init__(self, log: CallLog, trusted_url: str, delay: float = 0.0) -> None:
        self.log = log
        self.trusted_url = trusted_url
        self.delay = delay

    def judge(self, question: Question, claims: Sequence[Claim], pairs: Sequence[Pair]) -> Judgment:
        self.log.record("judge")
        time.sleep(self.delay)
        return Judgment(
            answer="当前版本是 1.0",
            confidence=0.9,
            reasoning="测试数据",
            conflicts=(),
            trusted_sources=(self.trusted_url,),
            usage=USAGE,
        )


class _Timer:
    def __init__(self, due: float, interval: float, tick: Callable[[], None]) -> None:
        self.due = due
        self.interval = interval
        self.tick = tick


class FakeClock:
    """时间只在 advance 时前进。它同时是 Ticker：advance 跨过的每个计时点都在调用方线程里同步触发 tick。"""

    START = datetime(2026, 11, 19, 20, 0, 0, tzinfo=UTC)

    def __init__(self, start: datetime = START) -> None:
        self._start = start
        self._elapsed = 0.0
        self._timers: list[_Timer] = []

    def now(self) -> datetime:
        return self._start + timedelta(seconds=self._elapsed)

    def monotonic(self) -> float:
        return 1000.0 + self._elapsed

    def every(self, seconds: float, tick: Callable[[], None]) -> Callable[[], None]:
        timer = _Timer(self._elapsed + seconds, seconds, tick)
        self._timers.append(timer)
        return lambda: self._timers.remove(timer)

    @property
    def running_timers(self) -> int:
        return len(self._timers)

    def advance(self, seconds: float) -> None:
        target = self._elapsed + seconds
        while due := [timer for timer in self._timers if timer.due <= target]:
            timer = min(due, key=lambda t: t.due)
            self._elapsed = timer.due
            timer.due += timer.interval
            timer.tick()
        self._elapsed = target


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[Event] = []
        self._lock = threading.Lock()

    def emit(self, event: Event) -> None:
        with self._lock:
            self.events.append(event)

    def types(self) -> list[str]:
        return [event.type for event in self.events]


class InMemoryRunRepository:
    def __init__(self) -> None:
        self.saved: list[RunResult] = []

    def save(self, result: RunResult) -> str:
        self.saved.append(result)
        return f"memory://{len(self.saved)}"


# 让 pyright 核对这些假实现确实满足端口协议。
_fetcher: type[PageFetcher] = FakeFetcher
_extractor: type[ClaimExtractor] = FakeExtractor
_pairers: tuple[type[ClaimPairer], ...] = (FakePairer, EqualityPairer)
_judge: type[VerdictJudge] = FakeJudge
_clock: type[Clock] = FakeClock
_ticker: type[Ticker] = FakeClock
_sink: type[EventSink] = RecordingSink
_runs: type[RunRepository] = InMemoryRunRepository
