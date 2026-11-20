"""自动建题库：出题 → 找来源 → 抓取 → 可用性与关键词过滤 → 写出 yaml。"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from crossfire.application.ports import PageFetcher, PageStore, QuestionProposer, SourceFinder
from crossfire.domain import (
    AsOf,
    BankQuestion,
    CandidateSource,
    DroppedQuestion,
    DropReason,
    KeptSource,
    Page,
    ProposedQuestion,
    RejectedSource,
    Source,
    Tier,
)

MIN_USABLE_SOURCES = 5
TIER_TARGETS = {Tier.PRIMARY: (2, 3), Tier.NEWS: (2, 3), Tier.AGGREGATOR: (2, 3)}
StoreFor = Callable[[str], PageStore]


@dataclass(frozen=True)
class BankEstimate:
    questions: int
    searches: int
    claude_requests: int
    steel_pages: int
    anthropic_usd: float
    search_usd: float
    steel_usd: float

    @property
    def total_anthropic_usd(self) -> float:
        return self.anthropic_usd + self.search_usd


def estimate_bank_build(
    question_count: int,
    *,
    searches_per_question: int,
    candidates_per_question: int,
    search_per_thousand_usd: float,
    sonnet_input_per_mtok: float,
    sonnet_output_per_mtok: float,
    steel_per_scrape_usd: float,
    propose_input_tokens: int = 2000,
    propose_output_tokens: int = 3000,
    find_input_tokens: int = 12000,
    find_output_tokens: int = 800,
) -> BankEstimate:
    """试点前的费用上限估算。token 数是经验值，偏高一点。"""
    searches = question_count * searches_per_question
    # 1 次出题 + 每题 1 次找来源
    claude_requests = 1 + question_count
    steel_pages = question_count * candidates_per_question
    token_usd = (
        (propose_input_tokens + question_count * find_input_tokens) * sonnet_input_per_mtok
        + (propose_output_tokens + question_count * find_output_tokens) * sonnet_output_per_mtok
    ) / 1_000_000
    search_usd = searches * search_per_thousand_usd / 1000
    steel_usd = steel_pages * steel_per_scrape_usd
    return BankEstimate(
        questions=question_count,
        searches=searches,
        claude_requests=claude_requests,
        steel_pages=steel_pages,
        anthropic_usd=token_usd,
        search_usd=search_usd,
        steel_usd=steel_usd,
    )


def page_mentions_topic(markdown: str | None, keywords: Sequence[str]) -> bool:
    """正文里至少命中一个关键词（大小写不敏感）。防网址被复用成别的文章。"""
    if not markdown or not keywords:
        return False
    text = markdown.casefold()
    return any(keyword.casefold() in text for keyword in keywords if keyword.strip())


def select_by_tier_mix(candidates: Sequence[CandidateSource]) -> list[CandidateSource]:
    """按层级配额挑 6–8 个：每层尽量 2–3 个，多出来的按出现顺序丢掉。"""
    buckets: dict[Tier, list[CandidateSource]] = {tier: [] for tier in Tier}
    for candidate in candidates:
        bucket = buckets[candidate.suggested_tier]
        _low, high = TIER_TARGETS[candidate.suggested_tier]
        if len(bucket) < high:
            bucket.append(candidate)
    picked = [item for tier in Tier for item in buckets[tier]]
    # 某层不足下限时，用其他层多出来的补不了——只返回已有的；后面靠总数门槛丢题。
    return picked


class BuildQuestionBank:
    def __init__(
        self,
        proposer: QuestionProposer,
        finder: SourceFinder,
        fetcher: PageFetcher,
        store_for: StoreFor,
        *,
        min_usable: int = MIN_USABLE_SOURCES,
    ) -> None:
        self._proposer = proposer
        self._finder = finder
        self._fetcher = fetcher
        self._store_for = store_for
        self._min_usable = min_usable

    def execute(self, count: int, as_of: AsOf) -> tuple[list[BankQuestion], list[DroppedQuestion]]:
        proposed = self._proposer.propose(count, as_of)
        kept: list[BankQuestion] = []
        dropped: list[DroppedQuestion] = []
        for item in proposed:
            result = self._process(item, as_of)
            if isinstance(result, BankQuestion):
                kept.append(result)
            else:
                dropped.append(result)
        return kept, dropped

    def _process(self, proposed: ProposedQuestion, today: AsOf) -> BankQuestion | DroppedQuestion:
        candidates = select_by_tier_mix(self._finder.find(proposed.text, today))
        if not candidates:
            return DroppedQuestion(
                proposed=proposed,
                reason=DropReason.TOO_FEW_USABLE,
                detail="SourceFinder 没有返回任何候选",
                rejected=(),
            )

        pages = self._fetcher.fetch_all([c.url for c in candidates])
        store = self._store_for(proposed.id)
        kept_sources: list[KeptSource] = []
        rejected: list[RejectedSource] = []
        seen: set[str] = set()

        for candidate, page in zip(candidates, pages, strict=True):
            store.save(page)
            decision = _reject_page(page, proposed.keywords, seen)
            if decision is not None:
                rejected.append(decision)
                continue
            seen.add(page.url)
            kept_sources.append(
                KeptSource(
                    source=Source(url=page.url, tier=candidate.suggested_tier),
                    title=candidate.title or (page.title or page.url),
                    query=candidate.query,
                )
            )

        if len(kept_sources) < self._min_usable:
            return DroppedQuestion(
                proposed=proposed,
                reason=DropReason.TOO_FEW_USABLE,
                detail=f"可用来源 {len(kept_sources)} 个，少于 {self._min_usable}",
                rejected=tuple(rejected),
            )
        return BankQuestion(
            id=proposed.id,
            text=proposed.text,
            category=proposed.category,
            language=proposed.language,
            generated_on=today,
            keywords=proposed.keywords,
            sources=tuple(kept_sources),
            rejected=tuple(rejected),
        )


def _reject_page(page: Page, keywords: Sequence[str], seen: set[str]) -> RejectedSource | None:
    if page.url in seen:
        return RejectedSource(page.url, DropReason.DUPLICATE_URL, "同一题里 URL 重复")
    if not page.ok:
        return RejectedSource(page.url, DropReason.FETCH_FAILED, page.error or "抓取失败")
    if not page.usable:
        return RejectedSource(
            page.url,
            DropReason.UNUSABLE_PAGE,
            page.unusable_reason.value if page.unusable_reason else "不可用",
        )
    if not page_mentions_topic(page.markdown, keywords):
        return RejectedSource(page.url, DropReason.KEYWORD_MISS, "正文未出现任何关键词")
    return None
