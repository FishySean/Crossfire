"""兼容门面，第 4 步删除。

run() 的签名和返回的 dict 跟原来一样，命令行和 web 端点一行不用改。它只做组装：
把 VerifyQuestion 和存储、时钟、心跳、事件回调拼起来，再把 RunResult 转回原来的 dict。
第 4 步的组合根接手组装之后，入口直接调用 VerifyQuestion，这个文件整个删掉。
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from crossfire.adapters.event_sinks import CallbackEventSink
from crossfire.application.ports import ClaimExtractor, ClaimPairer, PageFetcher, VerdictJudge
from crossfire.application.records import run_record
from crossfire.composition import assemble
from crossfire.domain import Mode, Question

RUNS_DIR = Path(__file__).resolve().parents[1] / "out" / "runs"
HEARTBEAT_SECONDS = 5


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

    use_case = assemble(
        fetcher,
        extractor,
        pairer,
        judge,
        runs_dir=RUNS_DIR,
        event_sink=CallbackEventSink(on_event) if on_event else None,
        heartbeat_seconds=HEARTBEAT_SECONDS,
    )
    saved = use_case.execute(question)
    return {**run_record(saved.result), "output_path": saved.location}
