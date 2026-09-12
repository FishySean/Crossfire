import asyncio
import json
import queue
import threading
import time
import traceback
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from crossfire.pipeline import run
from web.fake_events import SCENARIOS, scenario_events

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "out" / "runs"
QUESTIONS_FILE = ROOT / "questions" / "demo.yaml"
STATIC_DIR = Path(__file__).resolve().parent / "static"
READ_RETRIES = 3
RETRY_DELAY_SECONDS = 0.15

app = FastAPI(title="Crossfire Viewer")


@app.get("/api/runs")
def list_runs() -> list[dict]:
    if not RUNS_DIR.is_dir():
        return []
    runs = []
    for path in RUNS_DIR.glob("*.json"):
        runs.append({"name": path.name, "modified_at": path.stat().st_mtime})
    return sorted(runs, key=lambda r: (r["modified_at"], r["name"]), reverse=True)


@app.get("/api/runs/{name}")
def get_run(name: str) -> dict:
    path = (RUNS_DIR / name).resolve()
    if path.parent != RUNS_DIR.resolve() or path.suffix != ".json" or not path.is_file():
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


def _questions() -> list[dict]:
    if not QUESTIONS_FILE.is_file():
        return []
    return yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8")) or []


@app.get("/api/questions")
def list_questions() -> list[dict]:
    return [
        {
            "id": item["id"],
            "question": item.get("question", ""),
            "total_sources": len(item.get("sources", [])),
        }
        for item in _questions()
    ]


SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _frame(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.get("/api/run/{question_id}")
async def run_question(question_id: str, mode: str = "cached") -> StreamingResponse:
    """把 pipeline.run 的 on_event 回调转成 SSE 事件流。

    run 是同步阻塞的，而且内部自己调 asyncio.run，所以不能在这里 await：
    它跑在独立线程里，回调往线程安全队列里塞，下面的生成器从队列抽。
    """
    if mode not in ("live", "cached"):
        raise HTTPException(status_code=400, detail=f"unknown mode: {mode}")
    config = next((q for q in _questions() if q["id"] == question_id), None)
    if config is None:
        raise HTTPException(status_code=404, detail=f"unknown question: {question_id}")

    async def stream():
        events: queue.Queue = queue.Queue()
        finished = object()
        started = time.monotonic()

        def work() -> None:
            try:
                run(config, on_event=events.put, mode=mode)
            except Exception as e:
                traceback.print_exc()
                # 前端把「done 之前流就断了」当成事件流中断报错，所以失败也必须以 done 收尾。
                events.put({"type": "error", "step": "pipeline", "detail": f"{type(e).__name__}: {e}"})
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


@app.get("/api/fake-run/{scenario}")
async def fake_run(scenario: str, speed: float = 1.0) -> StreamingResponse:
    """Scripted event stream used to develop and rehearse the live view.

    Mirrors the agreed /api/run/{question_id} protocol so the frontend can be
    exercised end to end without the real pipeline.
    """
    if scenario not in SCENARIOS:
        raise HTTPException(status_code=404, detail=f"unknown scenario: {scenario}")

    async def stream():
        events = scenario_events(scenario)
        for delay, event in events:
            await asyncio.sleep(delay / max(speed, 0.01))
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        while not events:
            # "stall": hold the connection open without ever emitting an event.
            await asyncio.sleep(5)
            yield ": waiting\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
