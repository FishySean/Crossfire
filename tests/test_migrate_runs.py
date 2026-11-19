"""scripts/migrate_runs.py：默认演练不写文件；--apply 先整目录备份；可以重复跑。"""

import json

import pytest

from crossfire.config import Settings
from crossfire.domain import RunResult
from scripts.migrate_runs import main, migrate
from tests.test_domain import RUN

CURRENT = RunResult.from_dict(RUN).to_dict()


def old_format():
    """开始统计请求数、记录 mode 之前写出的文件长这样。"""
    data = json.loads(json.dumps(CURRENT))
    del data["mode"]
    for record in [*data["claims"], *data["pairs"], data["judgment"]]:
        del record["usage"]["requests"]
    for step in data["steps"].values():
        step.pop("requests", None)
    data["claude_calls"] = 3
    return data


def test_current_files_need_no_change():
    migrated, changes = migrate(CURRENT)
    assert changes == []
    assert migrated == CURRENT


def test_old_file_gets_mode_and_unrecorded_requests():
    migrated, changes = migrate(old_format())

    assert list(migrated)[:3] == ["question_id", "question", "mode"]
    assert migrated["mode"] == "live"
    assert all(r["usage"]["requests"] is None for r in [*migrated["claims"], *migrated["pairs"], migrated["judgment"]])
    assert [step.get("requests", "absent") for step in migrated["steps"].values()] == ["absent", None, None, None]
    assert migrated["claude_calls"] is None
    run = RunResult.from_dict(migrated)
    assert run.model_requests is None
    assert len(changes) == 4


def test_migration_is_idempotent():
    once, _ = migrate(old_format())
    twice, changes = migrate(once)
    assert changes == [] and twice == once


def test_conflicts_encoded_as_a_json_string_become_an_array():
    data = json.loads(json.dumps(CURRENT))
    data["judgment"]["conflicts"] = json.dumps(["甲", "乙"], ensure_ascii=False)
    migrated, changes = migrate(data)
    assert migrated["judgment"]["conflicts"] == ["甲", "乙"]
    assert "json.loads" in changes[0]


def test_conflicts_with_unescaped_quotes_are_split_on_the_item_separator():
    """真实文件里的样子：数组被编码成字符串，条目里的 "东京" 没转义，json.loads 解析不了。"""
    data = json.loads(json.dumps(CURRENT))
    data["judgment"]["conflicts"] = '["差异源于"东京"所指范围不同。", "第二条，含逗号。"]'
    migrated, _ = migrate(data)
    assert migrated["judgment"]["conflicts"] == ['差异源于"东京"所指范围不同。', "第二条，含逗号。"]
    RunResult.from_dict(migrated)


@pytest.mark.parametrize("text", ["随便一句话", '["含"引号", "", "b"]'])
def test_conflicts_that_cannot_be_recovered_are_refused(text):
    data = json.loads(json.dumps(CURRENT))
    data["judgment"]["conflicts"] = text
    with pytest.raises(ValueError):
        migrate(data)


@pytest.fixture
def runs(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "old.json").write_text(json.dumps(old_format(), ensure_ascii=False), encoding="utf-8")
    (runs_dir / "new.json").write_text(json.dumps(CURRENT, ensure_ascii=False), encoding="utf-8")
    settings = Settings.from_mapping({"CROSSFIRE_RUNS_DIR": str(runs_dir)}, env_file=tmp_path / ".env")
    return runs_dir, settings


def snapshot(directory):
    return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in sorted(directory.iterdir())}


def test_dry_run_writes_nothing(runs, capsys):
    runs_dir, settings = runs
    before = snapshot(runs_dir)

    assert main([], settings) == 0
    assert snapshot(runs_dir) == before
    assert sorted(p.name for p in runs_dir.parent.iterdir()) == ["runs"]
    out = capsys.readouterr().out
    assert "1 个要改" in out and "演练模式" in out


def test_apply_backs_up_then_migrates_and_a_second_run_does_nothing(runs, capsys):
    runs_dir, settings = runs
    original = snapshot(runs_dir)

    assert main(["--apply"], settings) == 0
    [backup] = [p for p in runs_dir.parent.iterdir() if p.name.startswith("runs.bak-")]
    assert {name: data for name, (data, _) in snapshot(backup).items()} == {
        name: data for name, (data, _) in original.items()
    }
    for path in runs_dir.glob("*.json"):
        RunResult.from_dict(json.loads(path.read_text(encoding="utf-8")))
    assert snapshot(runs_dir)["new.json"] == original["new.json"], "不用改的文件不该被重写"
    assert list(runs_dir.glob("*.tmp")) == []

    after_first = snapshot(runs_dir)
    assert main(["--apply"], settings) == 0
    assert snapshot(runs_dir) == after_first
    assert len([p for p in runs_dir.parent.iterdir() if p.name.startswith("runs.bak-")]) == 1
    assert "没有要改的文件" in capsys.readouterr().out


def test_a_file_that_cannot_be_migrated_is_reported_and_left_alone(runs, capsys):
    runs_dir, settings = runs
    broken = old_format()
    broken["judgment"]["conflicts"] = "不是数组"
    (runs_dir / "broken.json").write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
    before = (runs_dir / "broken.json").read_bytes()

    assert main(["--apply"], settings) == 1
    assert (runs_dir / "broken.json").read_bytes() == before
    assert "broken.json" in capsys.readouterr().out
