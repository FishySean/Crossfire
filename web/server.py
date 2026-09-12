import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

RUNS_DIR = Path(__file__).resolve().parents[1] / "out" / "runs"
STATIC_DIR = Path(__file__).resolve().parent / "static"

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
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"invalid JSON: {e}") from e


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
