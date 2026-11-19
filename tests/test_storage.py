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
