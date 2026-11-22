"""用户自提问：找来源 → 过滤 →（够用才）交给 VerifyQuestion。"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass

from crossfire.application.events import (
    AskCostRejected,
    Event,
    SourceCandidate,
    SourceFiltered,
    SourceSearchStart,
    SourcesInsufficient,
    SourcesReady,
)
from crossfire.application.ports import EventSink, PageFetcher, PageStore, SourceFinder
from crossfire.application.source_filter import keep_or_reject_pages, select_by_tier_mix
from crossfire.application.use_cases.verify_question import SavedRun, VerifyQuestion
from crossfire.domain import AsOf, Question, Tier
from crossfire.domain.pricing import ModelPrice

MIN_USABLE_SOURCES = 4
MAX_QUESTION_CHARS = 300
DEFAULT_MAX_COST_USD = 1.0

# 费用估算用的 per-call token 上限（宁可高估，不可低估）。
# 观测来源（2026-11-22）：
#   extract / judge：out/runs 四次真实 ask
#     - u-20261122-04825f0f（Node.js LTS，Steel+NLI）
#     - u-20261122-1d80d3f8（联合国秘书长，Steel+NLI）
#     - u-20261122-ad1d4074（Go，HTTP+NLI）
#     - tests/fixtures/ask_costs/go-20261122.json（第 8 步从零验证 Go，HTTP+NLI）
#   pair：out/runs 里 635 对 Claude 比对的 usage（NLI ask 的 pair usage 为 0）
#   find：ask 结果文件不含 SourceFinder 的 usage（找来源发生在 VerifyQuestion 之外），
#         故 FIND_* 保留偏高估常数，仅把 OUTPUT 从 800 提到 1000（max_tokens=4096）。
# 观测最大值 → 向上取整：
#   EXTRACT_INPUT  17743 → 18000 | EXTRACT_OUTPUT  317 → 350
#   PAIR_INPUT      2979 →  3000 | PAIR_OUTPUT     421 → 450
#   JUDGE_INPUT     8051 →  8500 | JUDGE_OUTPUT   1227 → 1300（judge max_tokens=3000）
#   FIND_INPUT   （未记录）12000 | FIND_OUTPUT （未记录）1000
SEARCHES_PER_QUESTION = 6
CANDIDATES_PER_QUESTION = 8
FIND_INPUT_TOKENS = 12000
FIND_OUTPUT_TOKENS = 1000
EXTRACT_INPUT_TOKENS = 18000
EXTRACT_OUTPUT_TOKENS = 350
PAIR_INPUT_TOKENS = 3000
PAIR_OUTPUT_TOKENS = 450
JUDGE_INPUT_TOKENS = 8500
JUDGE_OUTPUT_TOKENS = 1300


@dataclass(frozen=True)
class AskEstimate:
    searches: int
    steel_pages: int
    extract_calls: int
    pair_calls: int
    judge_calls: int
    search_usd: float
    steel_usd: float
    anthropic_usd: float
    pair_usd: float
    pairer_free: bool
    max_cost_usd: float
    # 展示用区间：4 来源下限 ～ 8 来源上限（与 total_usd 所用的 usable_sources 无关）。
    low_usd: float
    high_usd: float
    low_sources: int = MIN_USABLE_SOURCES
    high_sources: int = CANDIDATES_PER_QUESTION

    @property
    def total_usd(self) -> float:
        return self.search_usd + self.steel_usd + self.anthropic_usd + self.pair_usd

    @property
    def over_budget(self) -> bool:
        return self.total_usd > self.max_cost_usd

    def to_dict(self) -> dict[str, object]:
        return {
            "searches": self.searches,
            "steel_pages": self.steel_pages,
            "extract_calls": self.extract_calls,
            "pair_calls": self.pair_calls,
            "judge_calls": self.judge_calls,
            "search_usd": round(self.search_usd, 4),
            "steel_usd": round(self.steel_usd, 4),
            "anthropic_usd": round(self.anthropic_usd, 4),
            "pair_usd": round(self.pair_usd, 4),
            "pairer_free": self.pairer_free,
            "total_usd": round(self.total_usd, 4),
            "low_usd": round(self.low_usd, 4),
            "high_usd": round(self.high_usd, 4),
            "low_sources": self.low_sources,
            "high_sources": self.high_sources,
            "max_cost_usd": self.max_cost_usd,
            "over_budget": self.over_budget,
        }


@dataclass(frozen=True)
class AskStopped:
    """找来源后提前停止：不够用来源，或费用超限。"""

    reason: str
    detail: str
    estimate: AskEstimate
    found: int = 0
    kept: int = 0
    rejected: tuple[dict[str, str], ...] = ()
    question_id: str | None = None


@dataclass(frozen=True)
class AskResult:
    question: Question
    saved: SavedRun
    estimate: AskEstimate
    actual_cost_usd: float
    has_primary: bool
    question_file: str
    rejected: tuple[dict[str, str], ...]


BuildVerifier = Callable[..., VerifyQuestion]  # (question, has_primary=...)
StoreFor = Callable[[str], PageStore]
SaveQuestion = Callable[[Question, bool], str]
RecordCost = Callable[[str, float, AskEstimate], None]


def keywords_from_question(text: str) -> tuple[str, ...]:
    """从问题里抽关键词，给正文相关性过滤用。不是 NLP，够用即可。"""
    parts = re.findall(r"[A-Za-z][A-Za-z0-9.+-]{1,}|[\u4e00-\u9fff]{2,}", text)
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        key = part.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(part)
        if len(out) >= 12:
            break
    return tuple(out)


def make_user_question_id(text: str, when: AsOf) -> str:
    """短 id：日期 + 正文哈希前缀。绝不用用户原文拼路径。"""
    stamp = when.isoformat().replace("-", "")
    digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:8]
    return f"u-{stamp}-{digest}"


def validate_question_text(text: str) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        raise ValueError("问题不能为空")
    if len(cleaned) > MAX_QUESTION_CHARS:
        raise ValueError(f"问题最长 {MAX_QUESTION_CHARS} 字，当前 {len(cleaned)} 字")
    return cleaned


def _ask_cost_parts(
    *,
    usable_sources: int,
    pairer_free: bool,
    search_per_thousand_usd: float,
    steel_per_scrape_usd: float,
    sonnet_price: ModelPrice,
    pair_price: ModelPrice | None,
) -> tuple[int, int, float, float, float, float]:
    """返回 (extract_calls, pair_calls, search_usd, steel_usd, anthropic_usd, pair_usd)。"""
    n = max(usable_sources, MIN_USABLE_SOURCES)
    pairs = n * (n - 1) // 2
    find_usd = sonnet_price.cost_usd(FIND_INPUT_TOKENS, FIND_OUTPUT_TOKENS)
    extract_usd = sonnet_price.cost_usd(n * EXTRACT_INPUT_TOKENS, n * EXTRACT_OUTPUT_TOKENS)
    judge_usd = sonnet_price.cost_usd(JUDGE_INPUT_TOKENS, JUDGE_OUTPUT_TOKENS)
    if pairer_free:
        pair_usd = 0.0
        pair_calls = 0
    else:
        price = pair_price or sonnet_price
        pair_usd = price.cost_usd(pairs * PAIR_INPUT_TOKENS, pairs * PAIR_OUTPUT_TOKENS)
        pair_calls = pairs
    search_usd = SEARCHES_PER_QUESTION * search_per_thousand_usd / 1000
    steel_usd = CANDIDATES_PER_QUESTION * steel_per_scrape_usd
    return n, pair_calls, search_usd, steel_usd, find_usd + extract_usd + judge_usd, pair_usd


def estimate_ask_cost(
    *,
    pairer_free: bool,
    usable_sources: int = MIN_USABLE_SOURCES,
    max_cost_usd: float = DEFAULT_MAX_COST_USD,
    search_per_thousand_usd: float,
    steel_per_scrape_usd: float,
    sonnet_price: ModelPrice,
    pair_price: ModelPrice | None = None,
) -> AskEstimate:
    """按 usable_sources 估算本次费用，并附带 4～8 来源的展示区间。

    运行前的上限检查应传下限（默认 4）；来源确定后再用真实 n 估一次并再次检查上限。
    """
    n, pair_calls, search_usd, steel_usd, anthropic_usd, pair_usd = _ask_cost_parts(
        usable_sources=usable_sources,
        pairer_free=pairer_free,
        search_per_thousand_usd=search_per_thousand_usd,
        steel_per_scrape_usd=steel_per_scrape_usd,
        sonnet_price=sonnet_price,
        pair_price=pair_price,
    )
    _, _, low_search, low_steel, low_anth, low_pair = _ask_cost_parts(
        usable_sources=MIN_USABLE_SOURCES,
        pairer_free=pairer_free,
        search_per_thousand_usd=search_per_thousand_usd,
        steel_per_scrape_usd=steel_per_scrape_usd,
        sonnet_price=sonnet_price,
        pair_price=pair_price,
    )
    _, _, high_search, high_steel, high_anth, high_pair = _ask_cost_parts(
        usable_sources=CANDIDATES_PER_QUESTION,
        pairer_free=pairer_free,
        search_per_thousand_usd=search_per_thousand_usd,
        steel_per_scrape_usd=steel_per_scrape_usd,
        sonnet_price=sonnet_price,
        pair_price=pair_price,
    )
    return AskEstimate(
        searches=SEARCHES_PER_QUESTION,
        steel_pages=CANDIDATES_PER_QUESTION,
        extract_calls=n,
        pair_calls=pair_calls,
        judge_calls=1,
        search_usd=search_usd,
        steel_usd=steel_usd,
        anthropic_usd=anthropic_usd,
        pair_usd=pair_usd,
        pairer_free=pairer_free,
        max_cost_usd=max_cost_usd,
        low_usd=low_search + low_steel + low_anth + low_pair,
        high_usd=high_search + high_steel + high_anth + high_pair,
        low_sources=MIN_USABLE_SOURCES,
        high_sources=CANDIDATES_PER_QUESTION,
    )


class AskQuestion:
    """live 模式自提问。mode 固定 live；cached 重看走已有 verify 入口。"""

    def __init__(
        self,
        finder: SourceFinder,
        fetcher: PageFetcher,
        store_for: StoreFor,
        build_verifier: BuildVerifier,
        save_question: SaveQuestion,
        *,
        record_cost: RecordCost | None = None,
        event_sink: EventSink | None = None,
        min_usable: int = MIN_USABLE_SOURCES,
        max_cost_usd: float = DEFAULT_MAX_COST_USD,
        pairer_free: bool = False,
        search_per_thousand_usd: float,
        steel_per_scrape_usd: float,
        sonnet_price: ModelPrice,
        pair_price: ModelPrice | None = None,
        clock: Callable[[], AsOf],
    ) -> None:
        self._finder = finder
        self._fetcher = fetcher
        self._store_for = store_for
        self._build_verifier = build_verifier
        self._save_question = save_question
        self._record_cost = record_cost
        self._events = event_sink
        self._min_usable = min_usable
        self._max_cost_usd = max_cost_usd
        self._pairer_free = pairer_free
        self._search_per_thousand = search_per_thousand_usd
        self._steel_per_scrape = steel_per_scrape_usd
        self._sonnet_price = sonnet_price
        self._pair_price = pair_price
        self._clock = clock

    def estimate(self, question_text: str) -> AskEstimate:
        validate_question_text(question_text)
        return estimate_ask_cost(
            pairer_free=self._pairer_free,
            max_cost_usd=self._max_cost_usd,
            search_per_thousand_usd=self._search_per_thousand,
            steel_per_scrape_usd=self._steel_per_scrape,
            sonnet_price=self._sonnet_price,
            pair_price=self._pair_price,
        )

    def execute(self, question_text: str) -> AskResult | AskStopped:
        text = validate_question_text(question_text)
        estimate = self.estimate(text)
        if estimate.over_budget:
            self._emit(
                AskCostRejected(
                    total_usd=estimate.total_usd,
                    max_cost_usd=estimate.max_cost_usd,
                    sources=None,
                )
            )
            return AskStopped(
                reason="cost_limit",
                detail=(
                    f"预计 ${estimate.low_usd:.2f}～${estimate.high_usd:.2f}"
                    f"（{estimate.low_sources}～{estimate.high_sources} 个来源）"
                    f"超过上限 ${estimate.max_cost_usd:.2f}"
                ),
                estimate=estimate,
            )

        today = self._clock()
        question_id = make_user_question_id(text, today)
        keywords = keywords_from_question(text)
        self._emit(SourceSearchStart(question=text, question_id=question_id))

        candidates = self._finder.find(text, today)
        for candidate in candidates:
            self._emit(
                SourceCandidate(
                    url=candidate.url,
                    title=candidate.title,
                    tier=candidate.suggested_tier.value,
                )
            )

        selected = select_by_tier_mix(candidates)
        pages = self._fetcher.fetch_all([c.url for c in selected]) if selected else []
        store = self._store_for(question_id)
        for page in pages:
            store.save(page)

        kept, rejected = keep_or_reject_pages(selected, pages, keywords)
        rejected_rows = tuple(
            {"url": item.url, "reason": item.reason.value, "detail": item.detail} for item in rejected
        )
        for row in rejected_rows:
            self._emit(SourceFiltered(url=row["url"], reason=row["reason"], detail=row["detail"]))

        if len(kept) < self._min_usable:
            detail = (
                f"可用来源 {len(kept)} 个，少于 {self._min_usable}；"
                f"候选 {len(candidates)}，抓取 {len(selected)}，过滤 {len(rejected)}"
            )
            self._emit(
                SourcesInsufficient(
                    kept=len(kept),
                    found=len(candidates),
                    filtered=len(rejected),
                    detail=detail,
                )
            )
            return AskStopped(
                reason="too_few_sources",
                detail=detail,
                estimate=estimate,
                found=len(candidates),
                kept=len(kept),
                rejected=rejected_rows,
                question_id=question_id,
            )

        sources = tuple(item.source for item in kept)
        has_primary = any(source.tier is Tier.PRIMARY for source in sources)
        question = Question(id=question_id, text=text, sources=sources)

        # 来源数确定后用真实 n 再估；超限则在提取前停下（运行前只按 4 来源下限查过）。
        final_estimate = estimate_ask_cost(
            pairer_free=self._pairer_free,
            usable_sources=len(sources),
            max_cost_usd=self._max_cost_usd,
            search_per_thousand_usd=self._search_per_thousand,
            steel_per_scrape_usd=self._steel_per_scrape,
            sonnet_price=self._sonnet_price,
            pair_price=self._pair_price,
        )
        if final_estimate.over_budget:
            detail = (
                f"找到 {len(sources)} 个来源，预计 ${final_estimate.total_usd:.2f}，"
                f"超过上限 ${final_estimate.max_cost_usd:.2f}，已停止"
            )
            self._emit(
                AskCostRejected(
                    total_usd=final_estimate.total_usd,
                    max_cost_usd=final_estimate.max_cost_usd,
                    sources=len(sources),
                )
            )
            return AskStopped(
                reason="cost_limit",
                detail=detail,
                estimate=final_estimate,
                found=len(candidates),
                kept=len(sources),
                rejected=rejected_rows,
                question_id=question_id,
            )

        self._emit(
            SourcesReady(
                count=len(sources),
                has_primary=has_primary,
                urls=[source.url for source in sources],
            )
        )
        question_file = self._save_question(question, has_primary)
        verifier = self._build_verifier(question, has_primary=has_primary)
        saved = verifier.execute(question)
        actual = _actual_cost_usd(
            saved.result.total_input_tokens,
            saved.result.total_output_tokens,
            searches=estimate.searches,
            steel_pages=len(selected),
            search_per_thousand_usd=self._search_per_thousand,
            steel_per_scrape_usd=self._steel_per_scrape,
            sonnet_price=self._sonnet_price,
            pairer_free=self._pairer_free,
        )
        if self._record_cost is not None:
            self._record_cost(saved.location, actual, final_estimate)
        return AskResult(
            question=question,
            saved=saved,
            estimate=final_estimate,
            actual_cost_usd=actual,
            has_primary=has_primary,
            question_file=str(question_file),
            rejected=rejected_rows,
        )

    def _emit(self, event: Event) -> None:
        if self._events is not None:
            self._events.emit(event)


def _actual_cost_usd(
    input_tokens: int,
    output_tokens: int,
    *,
    searches: int,
    steel_pages: int,
    search_per_thousand_usd: float,
    steel_per_scrape_usd: float,
    sonnet_price: ModelPrice,
    pairer_free: bool,
) -> float:
    # NLI 比对不产生 Claude token；token 费用按结果文件总量估。
    token_usd = sonnet_price.cost_usd(input_tokens, output_tokens)
    search_usd = searches * search_per_thousand_usd / 1000
    steel_usd = steel_pages * steel_per_scrape_usd
    del pairer_free
    return round(token_usd + search_usd + steel_usd, 4)
