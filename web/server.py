import asyncio
import json
import time
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

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


@app.get("/api/questions")
def list_questions() -> list[dict]:
    if not QUESTIONS_FILE.is_file():
        return []
    config = yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8")) or []
    return [
        {
            "id": item["id"],
            "question": item.get("question", ""),
            "total_sources": len(item.get("sources", [])),
        }
        for item in config
    ]


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
