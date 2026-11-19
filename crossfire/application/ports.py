"""业务流程依赖的外部能力。每个端口只描述一种能力，实现放在 crossfire/adapters/。

端口全是同步接口。并发、异步、批量调度都是适配器内部的事，不泄漏到业务层。
"""

from collections.abc import Callable, Sequence
from typing import Protocol

from crossfire.domain import Claim, Judgment, Page, Pair, Question, Source, SourceIndex

type OnPage = Callable[[SourceIndex, Page], None]
type OnPair = Callable[[int, int, Pair], None]


class PageFetcher(Protocol):
    def fetch_all(self, urls: Sequence[str], on_page: OnPage | None = None) -> list[Page]:
        """按 urls 的顺序返回页面，每个 URL 恰好一页。

        单个页面抓取失败不抛异常，而是返回 ok=False 的 Page。
        on_page 在每页就绪时调用一次，index 是该页在 urls 里的下标；调用顺序是完成顺序，不保证有序。
        """
        ...


class ClaimExtractor(Protocol):
    def extract(self, question: Question, page: Page, source: Source) -> Claim:
        """从一个已抓到的页面里提取针对问题的主张。失败时返回带 failure 的 Claim，不抛异常。"""
        ...


class ClaimPairer(Protocol):
    def pair_all(
        self,
        question: Question,
        claim_pairs: Sequence[tuple[Claim, Claim]],
        on_pair: OnPair | None = None,
    ) -> list[Pair]:
        """一次判定一整批主张对，返回与 claim_pairs 一一对应、顺序相同的 Pair。

        必须是批量接口而不是一次一对：不同实现最快的调度方式完全不同。
        Claude 这类远程 API 一次只能问一对，最快的办法是在内部并发发请求；
        本地 NLI 小模型在 GPU 上跑，要一次塞进 32 到 64 对做批量推理才能把显卡用满。
        接口如果规定一次一对，GPU 实现就只能逐对计算，显卡大部分时间在空等。
        把整批交给实现，两边都能用各自最快的方式。

        on_pair(index, total, pair) 在每对判定完成时调用一次，index 是它在 claim_pairs 里的下标，
        调用顺序是完成顺序。单对失败时返回带 failure 的 Pair，不抛异常。
        """
        ...


class VerdictJudge(Protocol):
    def judge(self, question: Question, claims: Sequence[Claim], pairs: Sequence[Pair]) -> Judgment:
        """综合所有主张和比对结果下最终结论。失败时返回带 failure 的 Judgment，不抛异常。"""
        ...
