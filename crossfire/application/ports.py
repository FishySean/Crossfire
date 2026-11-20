"""业务流程依赖的外部能力。每个端口只描述一种能力，实现放在 crossfire/adapters/。

端口全是同步接口。并发、异步、批量调度都是适配器内部的事，不泄漏到业务层。
"""

from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import Protocol

from crossfire.application.events import Event
from crossfire.domain import Claim, Judgment, Mode, Page, Pair, Provenance, Question, RunResult, SourceIndex

type OnPage = Callable[[SourceIndex, Page], None]
type OnPair = Callable[[int, int, Pair], None]


class PageFetcher(Protocol):
    @property
    def mode(self) -> Mode:
        """这个实现是实时抓取还是读缓存。结果文件里的 mode 只从这里来，调用方不再另传一份。"""
        ...

    def fetch_all(self, urls: Sequence[str], on_page: OnPage | None = None) -> list[Page]:
        """按 urls 的顺序返回页面，每个 URL 恰好一页。

        单个页面抓取失败不抛异常，而是返回 ok=False 的 Page。
        on_page 在每页就绪时调用一次，index 是该页在 urls 里的下标；调用顺序是完成顺序，不保证有序。
        """
        ...


class ClaimExtractor(Protocol):
    @property
    def provenance(self) -> Provenance:
        """产出主张的模型和 prompt 版本，写进结果文件。"""
        ...

    def extract(self, question: Question, page: Page, as_of: date) -> Claim:
        """从一个已抓到的页面里提取针对问题的主张。来源层级用 question.source_of(page.url) 查。

        as_of 是这次查证的「今天」，必须照实告诉模型。
        实现里不许自己取当前时间：cached 模式和评测时，「今天」是快照那天，不是运行那天。
        失败时返回带 failure 的 Claim，不抛异常。
        """
        ...


class ClaimPairer(Protocol):
    @property
    def provenance(self) -> Provenance:
        """产出比对结果的模型和 prompt 版本。本地 NLI 模型写模型名和权重版本，没有 prompt。"""
        ...

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

        整批失败（比如 GPU 推理整批报错、远程调用抛了异常）时，同样不抛：把受影响的每一对都返回成
        带 failure 的 Pair，并照常对每一对调用 on_pair。原因是走到比对这一步时，抓取和提取已经做完、
        钱已经花了；抛异常会让整次运行作废，这些结果全部白费。返回失败的 Pair 则会进入
        RunResult.failures，并通过 error 事件通知前端，失败照样是大声的，判决也还能基于已有主张给出结论。
        """
        ...


class VerdictJudge(Protocol):
    @property
    def provenance(self) -> Provenance: ...

    def judge(self, question: Question, claims: Sequence[Claim], pairs: Sequence[Pair], as_of: date) -> Judgment:
        """综合所有主张和比对结果下最终结论。as_of 的要求同 ClaimExtractor.extract。

        失败时返回带 failure 的 Judgment，不抛异常。
        """
        ...


class RunRepository(Protocol):
    def save(self, result: RunResult) -> str:
        """保存一次运行的完整结果，返回保存位置。

        必须是原子的：读者要么看不到它，要么看到完整的内容，不会读到写了一半的文件。
        两次保存不许互相覆盖，哪怕 question 和 started_at 完全相同。
        """
        ...


class PageStore(Protocol):
    def save(self, page: Page) -> str:
        """存下一个抓到的页面（抓取失败的也存），返回保存位置。同一 URL 再存一次就覆盖。

        页面必须带 fetched_at，没有就抛异常：缓存是给 cached 模式当快照用的，不知道日期的快照没法用。
        """
        ...


class EventSink(Protocol):
    def emit(self, event: Event) -> None:
        """推送一个进度事件。可能从后台线程调用（心跳），实现需要自己保证线程安全。"""
        ...


class Clock(Protocol):
    def now(self) -> datetime:
        """带时区的当前 UTC 时间，用于记录运行开始的时刻。"""
        ...

    def monotonic(self) -> float:
        """单调递增的秒数，只用来算耗时。"""
        ...


class Ticker(Protocol):
    def every(self, seconds: float, tick: Callable[[], None]) -> Callable[[], None]:
        """从现在起每隔 seconds 秒调用一次 tick，直到调用返回的 stop。

        stop 返回之后保证不会再调用 tick。tick 可能在另一个线程里被调用。
        """
        ...
