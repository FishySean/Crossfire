"""scripts/make_sample_runs.py：写出的样例文件就是当前格式，能原样读回。"""

import json
import sys

from crossfire.application.records import run_record
from crossfire.domain import RunResult
from scripts import make_sample_runs


def test_sample_runs_round_trip_in_the_current_format(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["make_sample_runs.py", "--out", str(tmp_path)])
    make_sample_runs.main()
    files = sorted(tmp_path.glob("*.json"))
    assert [f.name.split("_")[0] for f in files] == ["python-latest-version", "sample-all-agree", "sample-with-failures"]
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert run_record(RunResult.from_dict(data)) == data


def test_sample_pages_are_usable_unless_meant_to_fail():
    assert all(page.usable for page in make_sample_runs.base_run().pages)
    failures = make_sample_runs.failures_run()
    assert [failure.step for failure in failures.failures] == ["fetch", "pair"]
