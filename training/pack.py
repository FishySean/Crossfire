"""把一次训练 run 打成可下载包：最终模型（fp16）+ 报告/曲线，不含其它种子权重。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from training.evaluate import predict_labels
from training.loop import assert_ready_to_train
from training.prepare import prepare_from_pairs


OPTIMIZER_FILE_NAMES = frozenset(
    {
        "optimizer.pt",
        "optimizer.pth",
        "scheduler.pt",
        "scaler.pt",
        "training_args.bin",
        "trainer_state.json",
        "rng_state.pth",
    }
)


def _dir_size_bytes(path: Path) -> int:
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def _assert_no_optimizer_state(model_dir: Path) -> list[str]:
    found = [
        str(path.relative_to(model_dir))
        for path in model_dir.rglob("*")
        if path.is_file() and path.name in OPTIMIZER_FILE_NAMES
    ]
    if found:
        raise RuntimeError(f"打包目录里出现了优化器/训练状态文件：{found}")
    return found


def save_model_fp16(fp32_dir: Path, out_dir: Path) -> Path:
    """训练全程 fp32；打包时权重转成 fp16 以减小体积（约一半）。"""
    model = AutoModelForSequenceClassification.from_pretrained(fp32_dir, dtype=torch.float32)
    assert_ready_to_train(model)
    model.half()  # 仅导出；不是用半精度权重去训练
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir)
    tokenizer = AutoTokenizer.from_pretrained(fp32_dir)
    tokenizer.save_pretrained(out_dir)
    # 去掉可能误拷的训练状态
    for name in OPTIMIZER_FILE_NAMES:
        junk = out_dir / name
        if junk.exists():
            junk.unlink()
    _assert_no_optimizer_state(out_dir)
    return out_dir


def compare_fp16_fp32_predictions(
    *,
    fp32_dir: Path,
    fp16_dir: Path,
    pairs_path: Path,
    max_length: int,
    device: torch.device,
) -> dict[str, Any]:
    prepared = prepare_from_pairs(pairs_path)
    test_rows = list(prepared.test_rows)
    fp32, tok = _load(fp32_dir, device, dtype=torch.float32)
    fp16, _ = _load(fp16_dir, device, dtype=torch.float16)
    p32 = predict_labels(fp32, test_rows, tok, max_length=max_length)
    p16 = predict_labels(fp16, test_rows, tok, max_length=max_length)
    disagree = sum(a != b for a, b in zip(p32, p16, strict=True))
    return {
        "n_test": len(test_rows),
        "n_disagree": disagree,
        "disagree_rate": disagree / len(test_rows) if test_rows else 0.0,
    }


def _load(path: Path, device: torch.device, *, dtype: torch.dtype):
    model = AutoModelForSequenceClassification.from_pretrained(path, dtype=dtype)
    model.to(device)
    if dtype == torch.float32:
        assert_ready_to_train(model)
    tokenizer = AutoTokenizer.from_pretrained(path)
    return model, tokenizer


def pack_run_artifacts(
    run_dir: Path,
    pack_dir: Path,
    *,
    pairs_path: Path,
    max_length: int,
    device: torch.device | None = None,
) -> dict[str, Any]:
    """只打包：最终模型(fp16)、三种子报告/曲线、summary、run_meta。不含其它种子 checkpoint。"""
    run_dir = Path(run_dir)
    pack_dir = Path(pack_dir)
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)

    device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
    fp32_final = run_dir / "final_model"
    if not fp32_final.is_dir():
        raise FileNotFoundError(f"缺少最终模型目录：{fp32_final}")

    fp16_dir = pack_dir / "final_model_fp16"
    save_model_fp16(fp32_final, fp16_dir)
    cmp = compare_fp16_fp32_predictions(
        fp32_dir=fp32_final,
        fp16_dir=fp16_dir,
        pairs_path=pairs_path,
        max_length=max_length,
        device=device,
    )

    for name in ("summary.json", "run_meta.json", "test_report.json", "test_report.md"):
        src = run_dir / name
        if src.exists():
            shutil.copy2(src, pack_dir / name)

    seeds_out = pack_dir / "seeds"
    seeds_out.mkdir(exist_ok=True)
    for seed_dir in sorted((run_dir / "seeds").glob("seed_*")):
        dest = seeds_out / seed_dir.name
        dest.mkdir(exist_ok=True)
        for name in ("history.json", "loss_curve.png", "test_report.json"):
            src = seed_dir / name
            if src.exists():
                shutil.copy2(src, dest / name)
        # 明确不拷 best_checkpoint/

    (pack_dir / "fp16_vs_fp32.json").write_text(
        json.dumps(cmp, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    size = _dir_size_bytes(pack_dir)
    meta = {
        "pack_dir": str(pack_dir),
        "size_bytes": size,
        "size_mb": round(size / (1024 * 1024), 1),
        "fp16_vs_fp32": cmp,
        "contains_optimizer_state": False,
        "note": "最终模型为 fp16 导出；训练时参数始终为 fp32。未包含其它种子的 checkpoint。",
    }
    (pack_dir / "pack_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"打包完成：{pack_dir}  大小 {meta['size_mb']} MB")
    print(
        f"fp16 vs fp32 预测不同：{cmp['n_disagree']} / {cmp['n_test']} "
        f"（{cmp['disagree_rate']:.2%}）"
    )
    return meta
