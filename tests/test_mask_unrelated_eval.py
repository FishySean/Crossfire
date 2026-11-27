"""mask_unrelated_eval：Drive 目录发现逻辑（不加载模型）。"""

from pathlib import Path

import pytest

from training.mask_unrelated_eval import (
    resolve_latest_complete_iter2_final,
    resolve_v1,
)


def _fake_ckpt(seed_dir: Path) -> None:
    ckpt = seed_dir / "best_checkpoint"
    ckpt.mkdir(parents=True)
    (ckpt / "config.json").write_text("{}", encoding="utf-8")
    (ckpt / "model.safetensors").write_bytes(b"x")


def test_resolve_v1_ok(tmp_path: Path):
    run = tmp_path / "run-20261121-235427"
    for seed in (42, 43, 44):
        _fake_ckpt(run / "seeds" / f"seed_{seed}")
    layout = resolve_v1(tmp_path)
    assert layout.name == "run-20261121-235427"
    assert set(layout.seed_dirs) == {42, 43, 44}


def test_resolve_v1_missing_loud(tmp_path: Path):
    (tmp_path / "other-run").mkdir()
    with pytest.raises(FileNotFoundError, match="找不到 v1"):
        resolve_v1(tmp_path)


def test_resolve_latest_complete_iter2_final(tmp_path: Path):
    incomplete = tmp_path / "iter2-final-20260101-000000"
    _fake_ckpt(incomplete / "seeds" / "seed_42")
    complete = tmp_path / "iter2-final-20260102-120000"
    for seed in (42, 43, 44):
        _fake_ckpt(complete / "seeds" / f"seed_{seed}")
    older_complete = tmp_path / "iter2-final-20260101-120000"
    for seed in (42, 43, 44):
        _fake_ckpt(older_complete / "seeds" / f"seed_{seed}")
    layout = resolve_latest_complete_iter2_final(tmp_path)
    assert layout.name == "iter2-final-20260102-120000"


def test_resolve_iter2_none_complete(tmp_path: Path):
    root = tmp_path / "iter2-final-20260101-000000"
    _fake_ckpt(root / "seeds" / "seed_42")
    with pytest.raises(FileNotFoundError, match="没有「三种子"):
        resolve_latest_complete_iter2_final(tmp_path)
