"""抓取后的来源过滤：建题库和用户提问共用，避免两套规则漂移。"""

from collections.abc import Sequence

from crossfire.domain import (
    CandidateSource,
    DropReason,
    KeptSource,
    Page,
    RejectedSource,
    Source,
    Tier,
)

TIER_TARGETS = {Tier.PRIMARY: (2, 3), Tier.NEWS: (2, 3), Tier.AGGREGATOR: (2, 3)}


def page_mentions_topic(markdown: str | None, keywords: Sequence[str]) -> bool:
    if not markdown or not keywords:
        return False
    text = markdown.casefold()
    return any(keyword.casefold() in text for keyword in keywords if keyword.strip())


def select_by_tier_mix(candidates: Sequence[CandidateSource]) -> list[CandidateSource]:
    buckets: dict[Tier, list[CandidateSource]] = {tier: [] for tier in Tier}
    for candidate in candidates:
        bucket = buckets[candidate.suggested_tier]
        _low, high = TIER_TARGETS[candidate.suggested_tier]
        if len(bucket) < high:
            bucket.append(candidate)
    return [item for tier in Tier for item in buckets[tier]]


def reject_page(page: Page, keywords: Sequence[str], seen: set[str]) -> RejectedSource | None:
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


def keep_or_reject_pages(
    candidates: Sequence[CandidateSource],
    pages: Sequence[Page],
    keywords: Sequence[str],
) -> tuple[list[KeptSource], list[RejectedSource]]:
    kept: list[KeptSource] = []
    rejected: list[RejectedSource] = []
    seen: set[str] = set()
    for candidate, page in zip(candidates, pages, strict=True):
        decision = reject_page(page, keywords, seen)
        if decision is not None:
            rejected.append(decision)
            continue
        seen.add(page.url)
        kept.append(
            KeptSource(
                source=Source(url=page.url, tier=candidate.suggested_tier),
                title=candidate.title or (page.title or page.url),
                query=candidate.query,
            )
        )
    return kept, rejected
