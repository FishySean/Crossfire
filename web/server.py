"""HTTP 和 SSE。组装交给 composition，配置交给 config，这里只管请求、响应和事件流。"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
import traceback
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import crossfire.composition as composition
from crossfire.application.events import Error
from crossfire.application.use_cases import VerifyQuestion
from crossfire.application.use_cases.ask_question import AskQuestion, AskResult, AskStopped, validate_question_text
from crossfire.config import Pairer, Settings, load_questions
from crossfire.domain import Mode, Question
from web.fake_events import SCENARIOS, scenario_events

STATIC_DIR = Path(__file__).resolve().parent / "static"
READ_RETRIES = 3
RETRY_DELAY_SECONDS = 0.15
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

BuildVerifier = Callable[..., VerifyQuestion]
BuildAsk = Callable[..., AskQuestion]


class AskBody(BaseModel):
    question: str = Field(min_length=1)
    pairer: str = Pairer.CLAUDE.value


def _frame(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _pairer_label(data: dict[str, Any]) -> str:
    """从结果文件里读比对器显示名；旧文件没有 provenance 时返回「未记录」。"""
    provenance = data.get("provenance")
    if not isinstance(provenance, dict):
        return "未记录"
    pair = provenance.get("pair")
    if not isinstance(pair, dict):
        return "未记录"
    implementation = pair.get("implementation")
    if implementation == "nli":
        model = str(pair.get("model") or "nli")
        short = Path(model).name if "/" in model or model.startswith(".") else model
        rev = pair.get("revision")
        if isinstance(rev, str) and rev:
            return f"NLI · {short} @ {rev[:7]}"
        return f"NLI · {short}"
    model = pair.get("model")
    if isinstance(model, str) and model:
        return f"Claude · {model}"
    return "未记录"


def create_app(
    settings: Settings | None = None,
    build_verifier: BuildVerifier | None = None,
    build_ask: BuildAsk | None = None,
) -> FastAPI:
    """settings 不传时读 .env，但什么 key 都不要求：只看历史结果不需要 key，缺 key 到发起查证时才报。"""
    settings = settings or Settings.from_env()
    build = build_verifier or composition.build_verifier
    ask_builder = build_ask or composition.build_ask_question
    runs_dir = settings.runs_dir
    app = FastAPI(title="Crossfire Viewer")

    @app.get("/api/runs")
    def list_runs() -> list[dict[str, Any]]:
        if not runs_dir.is_dir():
            return []
        runs: list[dict[str, Any]] = []
        for path in runs_dir.glob("*.json"):
            pairer = "未记录"
            question = ""
            started_at = None
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                pairer = _pairer_label(data)
                raw_q = data.get("question")
                if isinstance(raw_q, str):
                    question = raw_q
                elif isinstance(raw_q, dict) and isinstance(raw_q.get("text"), str):
                    question = raw_q["text"]
                elif isinstance(data.get("question_id"), str):
                    question = data["question_id"]
                started = data.get("started_at")
                if isinstance(started, str):
                    started_at = started
            except (OSError, json.JSONDecodeError, TypeError):
                pairer = "未记录"
            runs.append(
                {
                    "name": path.name,
                    "modified_at": path.stat().st_mtime,
                    "pairer": pairer,
                    "question": question,
                    "started_at": started_at,
                }
            )
        return sorted(runs, key=lambda r: (r["modified_at"], r["name"]), reverse=True)

    @app.get("/api/runs/{name}")
    def get_run(name: str) -> Any:
        from crossfire.application.summarize import summary_to_dict
        from crossfire.domain import RunResult

        path = (runs_dir / name).resolve()
        if path.parent != runs_dir.resolve() or path.suffix != ".json" or not path.is_file():
            raise HTTPException(status_code=404, detail="run not found")
        error: json.JSONDecodeError | None = None
        for attempt in range(READ_RETRIES):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                try:
                    data["summary"] = summary_to_dict(RunResult.from_dict(data))
                except (KeyError, TypeError, ValueError):
                    # 坏文件或半截写入：原样返回，不编造 summary。
                    data.setdefault("summary", None)
                return data
            except json.JSONDecodeError as e:
                error = e
                if attempt < READ_RETRIES - 1:
                    time.sleep(RETRY_DELAY_SECONDS)
        raise HTTPException(status_code=422, detail=f"invalid or partially written JSON: {error}")

    @app.get("/api/questions")
    def list_questions() -> list[dict[str, Any]]:
        return [
            {"id": q.id, "question": q.text, "total_sources": len(q.sources)} for q in load_questions(settings)
        ]

    @app.get("/api/pairers")
    def list_pairers() -> dict[str, Any]:
        return {
            "default": settings.pairer.value,
            "options": composition.pairer_availability(settings),
        }

    @app.get("/api/run/{question_id}")
    async def run_question(
        question_id: str,
        mode: str = "cached",
        pairer: str = Pairer.CLAUDE.value,
    ) -> StreamingResponse:
        """用例是同步阻塞的（Steel 适配器内部还会自己调 asyncio.run），所以不能在这里 await：
        它跑在独立线程里，事件进线程安全队列，下面的生成器从队列取出来转成 SSE。
        """
        try:
            run_mode = Mode(mode)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"unknown mode: {mode}") from None
        try:
            run_pairer = Pairer(pairer)
        except ValueError:
            allowed = "、".join(p.value for p in Pairer)
            raise HTTPException(status_code=400, detail=f"unknown pairer: {pairer}（可选：{allowed}）") from None
        question = next((q for q in load_questions(settings) if q.id == question_id), None)
        if question is None:
            raise HTTPException(status_code=404, detail=f"unknown question: {question_id}")

        async def stream() -> AsyncIterator[str]:
            events: queue.Queue[Any] = queue.Queue()
            finished = object()
            started = time.monotonic()

            def work() -> None:
                try:
                    build(
                        settings,
                        question,
                        run_mode,
                        composition.queue_event_sink(events),
                        pairer=run_pairer,
                    ).execute(question)
                except Exception as e:
                    traceback.print_exc()
                    # 前端把「done 之前流就断了」当成事件流中断报错，所以失败也必须以 done 收尾。
                    events.put(Error(step="pipeline", detail=f"{type(e).__name__}: {e}").to_dict())
                    events.put(
                        {"type": "done", "judgment": {}, "run_file": "", "elapsed": round(time.monotonic() - started, 2)}
                    )
                finally:
                    events.put(finished)

            threading.Thread(target=work, daemon=True).start()

            while True:
                event = await asyncio.to_thread(events.get)
                if event is finished:
                    return
                yield _frame(event)

        return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)

    @app.get("/api/fake-run/{scenario}")
    async def fake_run(scenario: str, speed: float = 1.0) -> StreamingResponse:
        """按剧本推送的假事件流，协议和 /api/run/{question_id} 一样，用来离线开发和排练前端。"""
        if scenario not in SCENARIOS:
            raise HTTPException(status_code=404, detail=f"unknown scenario: {scenario}")

        async def stream() -> AsyncIterator[str]:
            events = scenario_events(scenario)
            for delay, event in events:
                await asyncio.sleep(delay / max(speed, 0.01))
                yield _frame(event)
            while not events:
                # "stall"：连接一直开着，但永远不发事件。
                await asyncio.sleep(5)
                yield ": waiting\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)

    @app.post("/api/ask/estimate")
    def ask_estimate(body: AskBody) -> dict[str, Any]:
        try:
            text = validate_question_text(body.question)
            run_pairer = Pairer(body.pairer)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
        asker = ask_builder(settings, pairer=run_pairer)
        estimate = asker.estimate(text)
        return {
            "question": text,
            "pairer": run_pairer.value,
            "pairer_free": estimate.pairer_free,
            "estimate": estimate.to_dict(),
        }

    @app.post("/api/ask/run")
    async def ask_run(body: AskBody) -> StreamingResponse:
        """先由前端调 /api/ask/estimate 并确认，再 POST 这里开跑；SSE 推送找来源与查证进度。"""
        try:
            text = validate_question_text(body.question)
            run_pairer = Pairer(body.pairer)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None

        async def stream() -> AsyncIterator[str]:
            events: queue.Queue[Any] = queue.Queue()
            finished = object()
            started = time.monotonic()

            def work() -> None:
                try:
                    asker = ask_builder(
                        settings,
                        pairer=run_pairer,
                        event_sink=composition.queue_event_sink(events),
                    )
                    outcome = asker.execute(text)
                    if isinstance(outcome, AskStopped):
                        events.put(
                            {
                                "type": "ask_stopped",
                                "reason": outcome.reason,
                                "detail": outcome.detail,
                                "found": outcome.found,
                                "kept": outcome.kept,
                                "rejected": list(outcome.rejected),
                                "estimate": outcome.estimate.to_dict(),
                            }
                        )
                        events.put(
                            {
                                "type": "done",
                                "judgment": {},
                                "run_file": "",
                                "elapsed": round(time.monotonic() - started, 2),
                                "ask_stopped": True,
                            }
                        )
                    elif isinstance(outcome, AskResult):
                        events.put(
                            {
                                "type": "ask_finished",
                                "question_id": outcome.question.id,
                                "has_primary": outcome.has_primary,
                                "actual_cost_usd": outcome.actual_cost_usd,
                                "estimate": outcome.estimate.to_dict(),
                                "question_file": outcome.question_file,
                                "run_file": outcome.saved.location,
                            }
                        )
                except Exception as e:
                    traceback.print_exc()
                    events.put(Error(step="ask", detail=f"{type(e).__name__}: {e}").to_dict())
                    events.put(
                        {
                            "type": "done",
                            "judgment": {},
                            "run_file": "",
                            "elapsed": round(time.monotonic() - started, 2),
                        }
                    )
                finally:
                    events.put(finished)

            threading.Thread(target=work, daemon=True).start()

            while True:
                event = await asyncio.to_thread(events.get)
                if event is finished:
                    return
                yield _frame(event)

        return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
