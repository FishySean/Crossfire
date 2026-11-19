import json
import os
from pathlib import Path

from crossfire.application.records import run_record
from crossfire.domain import RunResult


class JsonRunRepository:
    """每次运行写成 runs_dir 下的一个 JSON 文件，文件名是 {question_id}_{开始时刻}.json。"""

    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = Path(runs_dir)

    def save(self, result: RunResult) -> str:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = result.started_at.strftime("%Y%m%dT%H%M%SZ")
        path = self.runs_dir / f"{result.question.id}_{timestamp}.json"
        # 先写同目录下的临时文件再 os.replace：rename 是原子的，web 端读历史结果时不会读到半截 JSON。
        staging = path.with_suffix(".json.tmp")
        staging.write_text(json.dumps(run_record(result), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(staging, path)
        return str(path)
