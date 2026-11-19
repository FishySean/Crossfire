"""把 pyright 零报错变成测试的一部分。配置在 pyproject.toml 的 [tool.pyright]。

domain 和 application 用 strict：SourceIndex 这类 NewType 只有类型检查器能拦住误用。
--outputjson 会让 pyright 跳过联网查新版本，并使用 wheel 自带的 pyright，全程离线。
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pyright_reports_no_errors():
    completed = subprocess.run(
        [sys.executable, "-m", "pyright", "--outputjson"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    report = json.loads(completed.stdout)
    errors = [
        f"{Path(d['file']).relative_to(ROOT)}:{d['range']['start']['line'] + 1}: {d['message']}"
        for d in report["generalDiagnostics"]
        if d["severity"] == "error"
    ]
    assert errors == [], "\n".join(errors)
    assert report["summary"]["filesAnalyzed"] > 0
