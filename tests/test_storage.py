"""JsonRunRepository：原子写入、写出的内容能原样读回。"""

import json
import os

from crossfire.adapters.storage import JsonRunRepository
from crossfire.application.records import run_record
from crossfire.domain import RunResult
from tests.test_domain import RUN

RESULT = RunResult.from_dict(RUN)


def test_saved_file_is_the_run_record_and_reads_back_as_the_same_result(tmp_path):
    location = JsonRunRepository(tmp_path).save(RESULT)

    on_disk = json.loads(open(location, encoding="utf-8").read())
    assert on_disk == run_record(RESULT)
    assert RunResult.from_dict(on_disk) == RESULT
    assert os.path.basename(location) == "q_20261119T200000Z.json"


def test_write_goes_through_a_temp_file_and_os_replace(tmp_path, monkeypatch):
    replaced = []
    real_replace = os.replace

    def spy_replace(src, dst):
        assert os.path.exists(src) and not os.path.exists(dst)
        replaced.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    location = JsonRunRepository(tmp_path).save(RESULT)

    assert replaced == [(location + ".tmp", location)]
    assert sorted(p.name for p in tmp_path.iterdir()) == [os.path.basename(location)]


def test_saves_in_the_same_second_do_not_overwrite_each_other(tmp_path):
    repository = JsonRunRepository(tmp_path)
    other = RunResult.from_dict({**RUN, "elapsed_seconds": 99.0})

    first = repository.save(RESULT)
    second = repository.save(other)
    third = repository.save(RESULT)

    assert [os.path.basename(p) for p in (first, second, third)] == [
        "q_20261119T200000Z.json",
        "q_20261119T200000Z_2.json",
        "q_20261119T200000Z_3.json",
    ]
    assert json.loads(open(first, encoding="utf-8").read())["elapsed_seconds"] == 12.5
    assert json.loads(open(second, encoding="utf-8").read())["elapsed_seconds"] == 99.0
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(os.path.basename(p) for p in (first, second, third))


def test_a_name_held_by_another_writer_is_skipped(tmp_path):
    """另一个进程正在写同名文件（它的 .tmp 还在）：不抢它的名字，也不动它的临时文件。"""
    (tmp_path / "q_20261119T200000Z.json.tmp").write_text("另一个写入者", encoding="utf-8")
    location = JsonRunRepository(tmp_path).save(RESULT)

    assert os.path.basename(location) == "q_20261119T200000Z_2.json"
    assert (tmp_path / "q_20261119T200000Z.json.tmp").read_text(encoding="utf-8") == "另一个写入者"
