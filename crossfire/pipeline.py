"""兼容门面，第 4 步删除。

run() 的签名和返回的 dict 跟原来一样，命令行和 web 端点一行不用改。它只做组装：
把 VerifyQuestion 和存储、时钟、心跳、事件回调拼起来，再把 RunResult 转回原来的 dict。
第 4 步的组合根接手组装之后，入口直接调用 VerifyQuestion，这个文件整个删掉。
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from crossfire.adapters.event_sinks import CallbackEventSink, NullEventSink
from crossfire.adapters.storage import JsonRunRepository
from crossfire.adapters.system import SystemClock, ThreadTicker
from crossfire.application.events import Done, Event
from crossfire.application.heartbeat import judge_with_heartbeat
from crossfire.application.ports import ClaimExtractor, ClaimPairer, EventSink, PageFetcher, VerdictJudge
from crossfire.application.records import run_record
from crossfire.application.use_cases import VerifyQuestion
from crossfire.domain import Mode, Question

RUNS_DIR = Path(__file__).resolve().parents[1] / "out" / "runs"
HEARTBEAT_SECONDS = 5


class _LegacySink:
    """把事件转成 dict 交给 on_event，并记下 done 事件里的保存位置，用来填旧返回值的 output_path。"""

    def __init__(self, on_event: Callable[[dict[str, Any]], None] | None) -> None:
        self._forward: EventSink = CallbackEventSink(on_event) if on_event else NullEventSink()
        self.run_file = ""

    def emit(self, event: Event) -> None:
        if isinstance(event, Done):
            self.run_file = event.run_file
        self._forward.emit(event)


def run(
    question: Question,
    fetcher: PageFetcher,
    extractor: ClaimExtractor,
    pairer: ClaimPairer,
    judge: VerdictJudge,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    mode: Mode | None = None,
) -> dict[str, Any]:
    """mode 只为兼容旧调用方保留：结果里的 mode 一律取自 fetcher，传了就必须和它一致。"""
    if mode is not None:
        if not isinstance(mode, Mode):
            raise TypeError(f"mode 必须是 Mode，收到 {mode!r}；字符串请在入口处用 Mode(...) 转换")
        if mode is not fetcher.mode:
            raise ValueError(f"传入的 mode={mode.value} 与注入的 fetcher（{fetcher.mode.value}）对不上")

    clock = SystemClock()
    sink = _LegacySink(on_event)
    listener = sink if on_event else None
    use_case = VerifyQuestion(
        fetcher=fetcher,
        extractor=extractor,
        pairer=pairer,
        judge=judge_with_heartbeat(judge, listener, clock, ThreadTicker(), HEARTBEAT_SECONDS),
        runs=JsonRunRepository(RUNS_DIR),
        events=sink,
        clock=clock,
    )
    result = use_case.execute(question)
    return {**run_record(result), "output_path": sink.run_file}
