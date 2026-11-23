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
from crossfire.domain import (
    AsOf,
    Claim,
    Failure,
    Judgment,
    Mode,
    Page,
    Pair,
    Provenance,
    Question,
    RunResult,
    SourceIndex,
    StepStats,
    as_of_for,
)


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

    @property
    def mode(self) -> Mode:
        return self._fetcher.mode

    @property
    def provenance(self) -> dict[str, Provenance]:
        return {
            "extract": self._extractor.provenance,
            "pair": self._pairer.provenance,
            "judge": self._judge.provenance,
        }

    def execute(self, question: Question) -> SavedRun:
        started_at = self._clock.now()
        started = self._clock.monotonic()
        self._events.emit(Start(question=question.text, total_sources=len(question.sources)))

        pages, fetch_stats = self._fetch_pages(question)
        as_of = as_of_for(self._fetcher.mode, started_at, pages)
        claims, extract_stats = self._extract_claims(question, pages, as_of)
        pairs, pair_stats = self._pair_claims(question, claims, as_of)
        judgment, judge_stats = self._reach_verdict(question, claims, pairs, as_of)

        result = RunResult(
            question=question,
            mode=self._fetcher.mode,
            started_at=started_at,
            as_of=as_of,
            elapsed_seconds=self._seconds_since(started),
            steps={"fetch": fetch_stats, "extract": extract_stats, "pair": pair_stats, "judge": judge_stats},
            provenance=self.provenance,
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
        # 第 7 步：内容不可用时带上原因；纯抓取失败 unusable_reason 仍为 None。
        unusable = failure.detail if failure is not None and failure.step == "usability" else None
        self._events.emit(
            FetchDone(
                url=page.url,
                ok=failure is None,
                chars=len(page.markdown or ""),
                index=index,
                unusable_reason=unusable,
            )
        )
        self._report(failure)

    def _extract_claims(self, question: Question, pages: list[Page], as_of: AsOf) -> tuple[list[Claim], StepStats]:
        started = self._clock.monotonic()
        usable = [page for page in pages if page.usable]

        def on_claim(position: int, claim: Claim) -> None:
            # position 是在 usable 里的下标。事件里的 index 必须换成来源在 sources 里的下标，跟 fetch_done 对齐：
            # 前端按它往固定的卡片槽位里填。直接用 position 会在有页面不可用时整体错位，把主张画到别的来源上。
            index = question.index_of(usable[position].url)
            self._events.emit(
                ClaimDone(
                    url=claim.source_url,
                    claim=claim.text,
                    tier=claim.tier.value,
                    index=index,
                    failed=claim.failure is not None,
                )
            )
            self._report(claim.failure)

        claims = self._extractor.extract_all(question, usable, as_of, on_claim)
        return claims, StepStats.summing([claim.usage for claim in claims], self._seconds_since(started))

    def _pair_claims(self, question: Question, claims: list[Claim], as_of: AsOf) -> tuple[list[Pair], StepStats]:
        claim_pairs = list(itertools.combinations([claim for claim in claims if claim.answered], 2))
        self._events.emit(PairStart(total_pairs=len(claim_pairs)))
        started = self._clock.monotonic()
        pairs = self._pairer.pair_all(question, claim_pairs, as_of, self._on_pair)
        return pairs, StepStats.summing([pair.usage for pair in pairs], self._seconds_since(started))

    def _on_pair(self, index: int, total: int, pair: Pair) -> None:
        relation = None if pair.relation is None else pair.relation.value
        self._events.emit(
            PairDone(
                pair.a_url,
                pair.b_url,
                relation,
                pair.nature,
                index=index,
                total=total,
                scores=None if pair.scores is None else dict(pair.scores),
            )
        )
        self._report(pair.failure)

    def _reach_verdict(
        self, question: Question, claims: list[Claim], pairs: list[Pair], as_of: AsOf
    ) -> tuple[Judgment, StepStats]:
        self._events.emit(JudgeStart())
        started = self._clock.monotonic()
        judgment = self._judge.judge(question, claims, pairs, as_of)
        stats = StepStats.summing([judgment.usage], self._seconds_since(started))
        self._report(judgment.failure)
        return judgment, stats

    def _save(self, result: RunResult) -> str:
        from crossfire.application.summarize import summary_to_dict

        location = self._runs.save(result)
        self._events.emit(
            Done(
                judgment=result.judgment,
                run_file=location,
                elapsed=result.elapsed_seconds,
                summary=summary_to_dict(result),
            )
        )
        return location

    def _report(self, failure: Failure | None) -> None:
        if failure is not None:
            self._events.emit(Error(step=failure.step, detail=failure.detail))

    def _seconds_since(self, started: float) -> float:
        return round(self._clock.monotonic() - started, 2)
