import itertools
from dataclasses import dataclass

from crossfire.application.events import (
    ClaimDone,
    Done,
    Error,
    FetchDone,
    JudgeStart,
    PairDone,
    PairStart,
    Start,
)
from crossfire.application.ports import (
    ClaimExtractor,
    ClaimPairer,
    Clock,
    EventSink,
    PageFetcher,
    RunRepository,
    VerdictJudge,
)
from crossfire.domain import Claim, Failure, Judgment, Page, Pair, Question, RunResult, SourceIndex, StepStats


@dataclass(frozen=True)
class SavedRun:
    """一次查证的结果和它保存的位置。用字段名取值，不用元组按位置取。"""

    result: RunResult
    location: str


class VerifyQuestion:
    """查证一个问题：抓取所有来源，逐页提取主张，两两比对，下结论，保存结果。

    每一步完成时通过 EventSink 推送进度事件，保存的位置也随最后的 done 事件发出。
    """

    def __init__(
        self,
        fetcher: PageFetcher,
        extractor: ClaimExtractor,
        pairer: ClaimPairer,
        judge: VerdictJudge,
        runs: RunRepository,
        events: EventSink,
        clock: Clock,
    ) -> None:
        self._fetcher = fetcher
        self._extractor = extractor
        self._pairer = pairer
        self._judge = judge
        self._runs = runs
        self._events = events
        self._clock = clock

    def execute(self, question: Question) -> SavedRun:
        started_at = self._clock.now()
        started = self._clock.monotonic()
        self._events.emit(Start(question=question.text, total_sources=len(question.sources)))

        pages, fetch_stats = self._fetch_pages(question)
        claims, extract_stats = self._extract_claims(question, pages)
        pairs, pair_stats = self._pair_claims(question, claims)
        judgment, judge_stats = self._reach_verdict(question, claims, pairs)

        result = RunResult(
            question=question,
            mode=self._fetcher.mode,
            started_at=started_at,
            elapsed_seconds=self._seconds_since(started),
            steps={"fetch": fetch_stats, "extract": extract_stats, "pair": pair_stats, "judge": judge_stats},
            pages=tuple(pages),
            claims=tuple(claims),
            pairs=tuple(pairs),
            judgment=judgment,
        )
        return SavedRun(result=result, location=self._save(result))

    def _fetch_pages(self, question: Question) -> tuple[list[Page], StepStats]:
        started = self._clock.monotonic()
        pages = self._fetcher.fetch_all([source.url for source in question.sources], self._on_page)
        return pages, StepStats(calls=len(pages), seconds=self._seconds_since(started))

    def _on_page(self, index: SourceIndex, page: Page) -> None:
        # 不可用的页面也报 ok=false：前端据此把卡片直接画成终态，不再等一条永远不会来的 claim_done。
        failure = page.failure
        self._events.emit(FetchDone(url=page.url, ok=failure is None, chars=len(page.markdown or ""), index=index))
        self._report(failure)

    def _extract_claims(self, question: Question, pages: list[Page]) -> tuple[list[Claim], StepStats]:
        started = self._clock.monotonic()
        claims: list[Claim] = []
        for page in (page for page in pages if page.usable):
            claim = self._extractor.extract(question, page)
            claims.append(claim)
            # index 必须是来源在 sources 里的下标，跟 fetch_done 对齐：前端按它往固定的卡片槽位里填。
            # 用 claims 的长度会在有页面抓取失败时整体错位，把主张画到别的来源上。
            index = question.index_of(page.url)
            self._events.emit(ClaimDone(url=claim.source_url, claim=claim.text, tier=claim.tier.value, index=index))
            self._report(claim.failure)
        return claims, StepStats.summing([claim.usage for claim in claims], self._seconds_since(started))

    def _pair_claims(self, question: Question, claims: list[Claim]) -> tuple[list[Pair], StepStats]:
        claim_pairs = list(itertools.combinations([claim for claim in claims if claim.answered], 2))
        self._events.emit(PairStart(total_pairs=len(claim_pairs)))
        started = self._clock.monotonic()
        pairs = self._pairer.pair_all(question, claim_pairs, self._on_pair)
        return pairs, StepStats.summing([pair.usage for pair in pairs], self._seconds_since(started))

    def _on_pair(self, index: int, total: int, pair: Pair) -> None:
        relation = None if pair.relation is None else pair.relation.value
        self._events.emit(PairDone(pair.a_url, pair.b_url, relation, pair.nature, index=index, total=total))
        self._report(pair.failure)

    def _reach_verdict(
        self, question: Question, claims: list[Claim], pairs: list[Pair]
    ) -> tuple[Judgment, StepStats]:
        self._events.emit(JudgeStart())
        started = self._clock.monotonic()
        judgment = self._judge.judge(question, claims, pairs)
        stats = StepStats.summing([judgment.usage], self._seconds_since(started))
        self._report(judgment.failure)
        return judgment, stats

    def _save(self, result: RunResult) -> str:
        location = self._runs.save(result)
        self._events.emit(Done(judgment=result.judgment, run_file=location, elapsed=result.elapsed_seconds))
        return location

    def _report(self, failure: Failure | None) -> None:
        if failure is not None:
            self._events.emit(Error(step=failure.step, detail=failure.detail))

    def _seconds_since(self, started: float) -> float:
        return round(self._clock.monotonic() - started, 2)
