"""自动建题库：出题 → 找来源 → 抓取 → 可用性与关键词过滤。

支持断点续跑：已成功的题目直接复用；余额中断的题目单独标记，续跑时只重做它们，
并按类别配额补齐缺口。余额不足时立刻抛错停下，不把中断当成「找不到来源」。
"""

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from crossfire.application.ports import PageFetcher, PageStore, QuestionProposer, SourceFinder
from crossfire.application.source_filter import keep_or_reject_pages, reject_page, select_by_tier_mix
from crossfire.domain import (
    AsOf,
    BankQuestion,
    DroppedQuestion,
    DropReason,
    ProposedQuestion,
    QuestionCategory,
    Tier,
)
from crossfire.domain.bank import CATEGORY_QUOTAS, question_text_hint_reason

MIN_USABLE_SOURCES = 5
MIN_PRIMARY_SOURCES = 1
StoreFor = Callable[[str], PageStore]
ProgressSaver = Callable[[list[BankQuestion], list[DroppedQuestion]], None]

# 对外仍从本模块导入这些名字（测试/__init__ 依赖）。
_reject_page = reject_page


class BankBuildInterrupted(Exception):
    """余额不足或鉴权失败。progress 里当前题已标成 interrupted，调用方应立刻停。"""

    def __init__(self, question_id: str, detail: str) -> None:
        super().__init__(detail)
        self.question_id = question_id
        self.detail = detail


@dataclass(frozen=True)
class BankEstimate:
    questions: int
    searches: int
    claude_requests: int
    steel_pages: int
    anthropic_usd: float
    search_usd: float
    steel_usd: float
    reuse: int = 0
    redo: int = 0

    @property
    def total_anthropic_usd(self) -> float:
        return self.anthropic_usd + self.search_usd


def estimate_bank_build(
    *,
    redo: int,
    propose: int,
    searches_per_question: int,
    candidates_per_question: int,
    search_per_thousand_usd: float,
    sonnet_input_per_mtok: float,
    sonnet_output_per_mtok: float,
    steel_per_scrape_usd: float,
    reuse: int = 0,
    find_input_tokens: int = 12000,
    find_output_tokens: int = 800,
    propose_input_tokens: int = 2000,
    propose_output_tokens: int = 3000,
) -> BankEstimate:
    """只估还要新做的部分。reuse 不花钱。"""
    find_calls = redo + propose
    propose_calls = 1 if propose else 0
    searches = find_calls * searches_per_question
    claude_requests = propose_calls + find_calls
    steel_pages = find_calls * candidates_per_question
    token_usd = (
        (propose_calls * propose_input_tokens + find_calls * find_input_tokens) * sonnet_input_per_mtok
        + (propose_calls * propose_output_tokens + find_calls * find_output_tokens) * sonnet_output_per_mtok
    ) / 1_000_000
    return BankEstimate(
        questions=reuse + redo + propose,
        searches=searches,
        claude_requests=claude_requests,
        steel_pages=steel_pages,
        anthropic_usd=token_usd,
        search_usd=searches * search_per_thousand_usd / 1000,
        steel_usd=steel_pages * steel_per_scrape_usd,
        reuse=reuse,
        redo=redo + propose,
    )


def remaining_quotas(kept: Sequence[BankQuestion], quotas: Mapping[QuestionCategory, int] = CATEGORY_QUOTAS) -> dict[QuestionCategory, int]:
    have = Counter(question.category for question in kept)
    return {category: max(0, need - have[category]) for category, need in quotas.items()}


def apply_keep_rules(question: BankQuestion, *, min_usable: int = MIN_USABLE_SOURCES) -> DroppedQuestion | None:
    """已有结果再过一遍现行规则。不通过就返回丢弃记录，通过返回 None。"""
    if len(question.sources) < min_usable:
        return DroppedQuestion(
            proposed=_as_proposed(question),
            reason=DropReason.TOO_FEW_USABLE,
            detail=f"可用来源 {len(question.sources)} 个，少于 {min_usable}",
            rejected=question.rejected,
        )
    primaries = sum(1 for item in question.sources if item.source.tier is Tier.PRIMARY)
    if primaries < MIN_PRIMARY_SOURCES:
        return DroppedQuestion(
            proposed=_as_proposed(question),
            reason=DropReason.NO_PRIMARY,
            detail=f"一手来源 {primaries} 个，至少要 {MIN_PRIMARY_SOURCES} 个",
            rejected=question.rejected,
        )
    return None


def _as_proposed(question: BankQuestion) -> ProposedQuestion:
    return ProposedQuestion(
        id=question.id,
        text=question.text,
        category=question.category,
        language=question.language,
        keywords=question.keywords,
    )


class BuildQuestionBank:
    def __init__(
        self,
        proposer: QuestionProposer,
        finder: SourceFinder,
        fetcher: PageFetcher,
        store_for: StoreFor,
        *,
        min_usable: int = MIN_USABLE_SOURCES,
        on_progress: ProgressSaver | None = None,
        quotas: Mapping[QuestionCategory, int] = CATEGORY_QUOTAS,
    ) -> None:
        self._proposer = proposer
        self._finder = finder
        self._fetcher = fetcher
        self._store_for = store_for
        self._min_usable = min_usable
        self._on_progress = on_progress
        self._quotas = dict(quotas)

    def execute(
        self,
        as_of: AsOf,
        *,
        kept: Sequence[BankQuestion] = (),
        dropped: Sequence[DroppedQuestion] = (),
        retry: Sequence[ProposedQuestion] = (),
    ) -> tuple[list[BankQuestion], list[DroppedQuestion]]:
        """续跑入口。kept/dropped/retry 来自进度文件；首次全空则按配额新出题。"""
        kept_list: list[BankQuestion] = []
        dropped_list = [item for item in dropped if item.reason is not DropReason.INTERRUPTED]

        # 已成功的再过现行规则；超配额的多出来移到 dropped（不重抓）。
        by_category: dict[QuestionCategory, list[BankQuestion]] = {category: [] for category in self._quotas}
        for question in kept:
            failure = apply_keep_rules(question, min_usable=self._min_usable)
            if failure is not None:
                dropped_list.append(failure)
                continue
            bucket = by_category[question.category]
            if len(bucket) < self._quotas[question.category]:
                bucket.append(question)
                kept_list.append(question)
            else:
                dropped_list.append(
                    DroppedQuestion(
                        proposed=_as_proposed(question),
                        reason=DropReason.TOO_FEW_USABLE,
                        detail=f"{question.category.value} 已满配额 {self._quotas[question.category]}，多出来的不保留",
                        rejected=question.rejected,
                    )
                )
        self._save(kept_list, dropped_list)

        # 余额中断的题目必须重做。
        for proposed in retry:
            if any(item.id == proposed.id for item in kept_list):
                continue
            self._run_one(proposed, as_of, kept_list, dropped_list)

        need = remaining_quotas(kept_list, self._quotas)
        if sum(need.values()) > 0:
            existing_ids = {item.id for item in kept_list} | {item.proposed.id for item in dropped_list}
            for proposed in self._proposer.propose(need, as_of):
                if proposed.id in existing_ids:
                    continue
                if need.get(proposed.category, 0) <= 0:
                    continue
                before = len(kept_list)
                self._run_one(proposed, as_of, kept_list, dropped_list)
                if len(kept_list) > before:
                    need[proposed.category] -= 1
                    existing_ids.add(proposed.id)
                if sum(need.values()) <= 0:
                    break

        return kept_list, dropped_list

    def _run_one(
        self,
        proposed: ProposedQuestion,
        as_of: AsOf,
        kept_list: list[BankQuestion],
        dropped_list: list[DroppedQuestion],
    ) -> None:
        # 清掉同 id 的旧 interrupted / 旧丢弃，避免进度里重复。
        dropped_list[:] = [item for item in dropped_list if item.proposed.id != proposed.id]
        try:
            result = self._process(proposed, as_of)
        except BankBuildInterrupted as error:
            dropped_list.append(
                DroppedQuestion(
                    proposed=proposed,
                    reason=DropReason.INTERRUPTED,
                    detail=error.detail,
                    rejected=(),
                )
            )
            self._save(kept_list, dropped_list)
            raise
        if isinstance(result, BankQuestion):
            if remaining_quotas(kept_list, self._quotas).get(result.category, 0) > 0:
                kept_list.append(result)
            else:
                dropped_list.append(
                    DroppedQuestion(
                        proposed=proposed,
                        reason=DropReason.TOO_FEW_USABLE,
                        detail=f"{result.category.value} 已满配额",
                        rejected=result.rejected,
                    )
                )
        else:
            dropped_list.append(result)
        self._save(kept_list, dropped_list)

    def _process(self, proposed: ProposedQuestion, today: AsOf) -> BankQuestion | DroppedQuestion:
        hint = question_text_hint_reason(proposed.text)
        if hint is not None:
            return DroppedQuestion(
                proposed=proposed,
                reason=DropReason.TOO_FEW_USABLE,
                detail=f"题目含答案提示（{hint}），拒绝入库",
                rejected=(),
            )
        try:
            found = self._finder.find(proposed.text, today)
        except Exception as error:
            if _is_credit_or_auth(error):
                raise BankBuildInterrupted(proposed.id, str(error)) from error
            raise

        candidates = select_by_tier_mix(found)
        if not candidates:
            return DroppedQuestion(
                proposed=proposed,
                reason=DropReason.TOO_FEW_USABLE,
                detail="SourceFinder 没有返回任何候选",
                rejected=(),
            )

        try:
            pages = self._fetcher.fetch_all([c.url for c in candidates])
        except Exception as error:
            if _is_credit_or_auth(error):
                raise BankBuildInterrupted(proposed.id, str(error)) from error
            raise

        store = self._store_for(proposed.id)
        for page in pages:
            store.save(page)
        kept_sources, rejected = keep_or_reject_pages(candidates, pages, proposed.keywords)

        if len(kept_sources) < self._min_usable:
            return DroppedQuestion(
                proposed=proposed,
                reason=DropReason.TOO_FEW_USABLE,
                detail=f"可用来源 {len(kept_sources)} 个，少于 {self._min_usable}",
                rejected=tuple(rejected),
            )
        primaries = sum(1 for item in kept_sources if item.source.tier is Tier.PRIMARY)
        if primaries < MIN_PRIMARY_SOURCES:
            return DroppedQuestion(
                proposed=proposed,
                reason=DropReason.NO_PRIMARY,
                detail=f"一手来源 {primaries} 个，至少要 {MIN_PRIMARY_SOURCES} 个",
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

    def _save(self, kept: list[BankQuestion], dropped: list[DroppedQuestion]) -> None:
        if self._on_progress:
            self._on_progress(kept, dropped)


def _is_credit_or_auth(error: BaseException) -> bool:
    detail = str(error).lower()
    return any(token in detail for token in ("credit balance", "insufficient", "authentication", "401", "403", "402"))
