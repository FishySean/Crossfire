"""HTTP 和 SSE。组装交给 composition，配置交给 config，这里只管请求、响应和事件流。"""

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

import crossfire.composition as composition
from crossfire.application.events import Error
from crossfire.application.use_cases import VerifyQuestion
from crossfire.config import Settings, load_questions
from crossfire.domain import Mode, Question
from web.fake_events import SCENARIOS, scenario_events

STATIC_DIR = Path(__file__).resolve().parent / "static"
READ_RETRIES = 3
RETRY_DELAY_SECONDS = 0.15
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

BuildVerifier = Callable[[Settings, Question, Mode, Any], VerifyQuestion]


def _frame(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def create_app(settings: Settings | None = None, build_verifier: BuildVerifier | None = None) -> FastAPI:
    """settings 不传时读 .env，但什么 key 都不要求：只看历史结果不需要 key，缺 key 到发起查证时才报。"""
    settings = settings or Settings.from_env()
    build = build_verifier or composition.build_verifier
    runs_dir = settings.runs_dir
    app = FastAPI(title="Crossfire Viewer")

    @app.get("/api/runs")
    def list_runs() -> list[dict[str, Any]]:
        if not runs_dir.is_dir():
            return []
        runs = [{"name": path.name, "modified_at": path.stat().st_mtime} for path in runs_dir.glob("*.json")]
        return sorted(runs, key=lambda r: (r["modified_at"], r["name"]), reverse=True)

    @app.get("/api/runs/{name}")
    def get_run(name: str) -> Any:
        path = (runs_dir / name).resolve()
        if path.parent != runs_dir.resolve() or path.suffix != ".json" or not path.is_file():
            raise HTTPException(status_code=404, detail="run not found")
        error: json.JSONDecodeError | None = None
        for attempt in range(READ_RETRIES):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
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

    @app.get("/api/run/{question_id}")
    async def run_question(question_id: str, mode: str = "cached") -> StreamingResponse:
        """用例是同步阻塞的（Steel 适配器内部还会自己调 asyncio.run），所以不能在这里 await：
        它跑在独立线程里，事件进线程安全队列，下面的生成器从队列取出来转成 SSE。
        """
        try:
            run_mode = Mode(mode)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"unknown mode: {mode}") from None
        question = next((q for q in load_questions(settings) if q.id == question_id), None)
        if question is None:
            raise HTTPException(status_code=404, detail=f"unknown question: {question_id}")

        async def stream() -> AsyncIterator[str]:
            events: queue.Queue[Any] = queue.Queue()
            finished = object()
            started = time.monotonic()

            def work() -> None:
                try:
                    build(settings, question, run_mode, composition.queue_event_sink(events)).execute(question)
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

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
