"""组合根：整个程序唯一 import adapters 的地方。

这里只做组装：按 Settings 选出每个端口的实现，new 出来，拼成用例交给入口。不写业务逻辑。
入口（crossfire/cli.py、web/server.py、app.py）只认识这里、config 和 domain。
"""

import queue
from pathlib import Path
from typing import Any

from crossfire.adapters.anthropic import ClaudeClaimExtractor, ClaudeClaimPairer, ClaudeClient, ClaudeVerdictJudge
from crossfire.adapters.anthropic.judge import JUDGE_PROMPT, without_sources_over_memory
from crossfire.adapters.event_sinks import NullEventSink, QueueEventSink
from crossfire.adapters.steel import CachedPageFetcher, SteelPageFetcher
from crossfire.adapters.storage import CachePageStore, JsonRunRepository
from crossfire.adapters.system import SystemClock, ThreadTicker
from crossfire.application.heartbeat import judge_with_heartbeat
from crossfire.application.ports import ClaimExtractor, ClaimPairer, EventSink, PageFetcher, VerdictJudge
from crossfire.application.use_cases import PrefetchPages, RunEvals, RunJudgeEvals, VerifyQuestion
from crossfire.config import Key, Pairer, Settings, eval_snapshot_dir
from crossfire.domain import Mode, Question
from crossfire.domain.evals import EvalCase

HEARTBEAT_SECONDS = 5

KEYS_FOR_MODE = {Mode.LIVE: (Key.ANTHROPIC, Key.STEEL), Mode.CACHED: (Key.ANTHROPIC,)}
KEYS_FOR_PREFETCH = (Key.STEEL,)


def build_verifier(
    settings: Settings,
    question: Question,
    mode: Mode,
    event_sink: EventSink | None = None,
) -> VerifyQuestion:
    if not isinstance(mode, Mode):
        raise TypeError(f"mode 必须是 Mode，收到 {mode!r}；字符串请在入口处用 Mode(...) 转换")
    settings.require(*KEYS_FOR_MODE[mode])
    return assemble(
        fetcher=build_fetcher(settings, question, mode),
        extractor=build_extractor(settings),
        pairer=build_pairer(settings),
        judge=ClaudeVerdictJudge(ClaudeClient(settings.anthropic_api_key, settings.model_judge)),
        runs_dir=settings.runs_dir,
        event_sink=event_sink,
    )


def build_eval_verifier(settings: Settings, case: EvalCase) -> VerifyQuestion:
    """评测只读这道题的冻结快照，结果写进单独的目录，不混进 out/runs 的历史记录。"""
    settings.require(*KEYS_FOR_MODE[Mode.CACHED])
    return assemble(
        fetcher=CachedPageFetcher(eval_snapshot_dir(settings, case)),
        extractor=build_extractor(settings),
        pairer=build_pairer(settings),
        judge=ClaudeVerdictJudge(ClaudeClient(settings.anthropic_api_key, settings.model_judge)),
        runs_dir=settings.eval_runs_dir / case.id,
    )


def build_eval_runner(settings: Settings) -> RunEvals:
    settings.require(*KEYS_FOR_MODE[Mode.CACHED])
    return RunEvals(lambda case, _question: build_eval_verifier(settings, case))


def build_judge_eval_runner(settings: Settings, *, drop_sources_over_memory: bool = False) -> RunJudgeEvals:
    """judge 题只调判决。drop_sources_over_memory 只给对照实验用：去掉判决 prompt 里「关于你自己的知识」那段。"""
    settings.require(*KEYS_FOR_MODE[Mode.CACHED])
    prompt = without_sources_over_memory() if drop_sources_over_memory else JUDGE_PROMPT
    return RunJudgeEvals(
        lambda _case: ClaudeVerdictJudge(ClaudeClient(settings.anthropic_api_key, settings.model_judge), prompt),
        SystemClock(),
    )


def assemble(
    fetcher: PageFetcher,
    extractor: ClaimExtractor,
    pairer: ClaimPairer,
    judge: VerdictJudge,
    runs_dir: Path,
    event_sink: EventSink | None = None,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> VerifyQuestion:
    """四个业务端口之外的零件都在这里配齐。测试注入假端口时也走这一条路，存储、时钟、心跳用的都是真的。"""
    clock = SystemClock()
    return VerifyQuestion(
        fetcher=fetcher,
        extractor=extractor,
        pairer=pairer,
        judge=judge_with_heartbeat(judge, event_sink, clock, ThreadTicker(), heartbeat_seconds),
        runs=JsonRunRepository(runs_dir),
        events=event_sink or NullEventSink(),
        clock=clock,
    )


def build_fetcher(settings: Settings, question: Question, mode: Mode) -> PageFetcher:
    if mode is Mode.CACHED:
        return CachedPageFetcher(settings.cache_dir / question.id)
    return SteelPageFetcher(settings.steel_api_key, clock=SystemClock())


def build_extractor(settings: Settings) -> ClaimExtractor:
    return ClaudeClaimExtractor(
        ClaudeClient(settings.anthropic_api_key, settings.model_extract), concurrency=settings.extract_concurrency
    )


def build_pairer(settings: Settings) -> ClaimPairer:
    match settings.pairer:
        case Pairer.CLAUDE:
            return ClaudeClaimPairer(ClaudeClient(settings.anthropic_api_key, settings.model_pair))


def build_prefetcher(settings: Settings, question: Question) -> PrefetchPages:
    settings.require(*KEYS_FOR_PREFETCH)
    return PrefetchPages(
        fetcher=SteelPageFetcher(settings.steel_api_key, clock=SystemClock()),
        store=CachePageStore(settings.cache_dir / question.id),
    )


def queue_event_sink(events: "queue.Queue[Any]") -> EventSink:
    """web 端用：事件转成 dict 放进线程安全队列，由 SSE 生成器取走。"""
    return QueueEventSink(events)
