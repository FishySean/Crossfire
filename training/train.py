"""正式训练入口：三种子、早停、打包结果。

主线在 Google Colab（免费 T4）；也可用 RunPod。用法见 training/README.md。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from training.amp import choose_amp, describe_device, make_grad_scaler
from training.config import DEFAULT_CONFIG, TrainConfig, config_to_dict
from training.evaluate import (
    always_agree_preds,
    base_native_preds,
    drop_identical,
    full_test_report,
    predict_labels,
)
from training.labels import ID2LABEL, LABEL2ID
from training.loop import (
    assert_ready_to_train,
    batch_encode,
    class_weight_tensor,
    eval_weighted_loss,
    train_step,
)
from training.metrics import macro_f1, summarize_seed_scores
from training.pack import pack_run_artifacts
from training.plot_curves import try_plot_loss_curves
from training.cv import grouped_kfold_by_question
from training.prepare import prepare_from_pairs
from training.resize_head import load_four_way_model
from training.split import load_pair_rows
from training.temperature import calibration_report, fit_temperature, stack_logits_labels


class PairDataset(Dataset):
    def __init__(self, rows: list[dict]) -> None:
        self.rows = list(rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict:
        return self.rows[index]


def _collate(tokenizer, max_length: int):
    def collate(rows: list[dict]):
        return batch_encode(rows, tokenizer, max_length=max_length)

    return collate


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def set_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def require_gpu(*, smoke: bool, allow_cpu: bool) -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if smoke or allow_cpu:
        print("警告：未检测到 GPU，按 --smoke / --allow-cpu 继续用 CPU（会很慢）。")
        return torch.device("cpu")
    raise SystemExit(
        "未检测到 GPU。正式训练必须在 GPU 上跑。\n"
        "Colab：菜单「代码执行程序 → 更改运行时类型」选 T4 GPU 后重跑。\n"
        "若只是本机冒烟，请加 --smoke 或 --allow-cpu。"
    )


def sync_seed_snapshot(run_dir: Path, seed: int, mirror_dir: Path | None) -> None:
    """每个种子结束后立刻镜像到 mirror（例如 Google Drive），断线不丢。"""
    if mirror_dir is None:
        return
    src = run_dir / "seeds" / f"seed_{seed}"
    dest = mirror_dir / "seeds" / f"seed_{seed}"
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    # 也刷新 run_meta，方便中途查看
    meta = run_dir / "run_meta.json"
    if meta.exists():
        shutil.copy2(meta, mirror_dir / "run_meta.json")
    print(f"已同步 seed={seed} → {dest}")


@dataclass
class SeedResult:
    seed: int
    best_epoch: int
    best_val_loss: float
    history: list[dict[str, Any]]
    checkpoint_dir: Path
    curve_path: Path | None


def _val_macro_f1(model, rows, tokenizer, max_length: int) -> float:
    y_true = [str(row["label"]) for row in rows]
    y_pred = predict_labels(model, rows, tokenizer, max_length=max_length)
    return macro_f1(y_true, y_pred)


def train_one_seed(
    *,
    config: TrainConfig,
    prepared,
    run_dir: Path,
    seed: int,
    device: torch.device,
    smoke: bool,
    mirror_dir: Path | None,
) -> SeedResult:
    set_seed(seed)
    seed_dir = run_dir / "seeds" / f"seed_{seed}"
    ckpt_dir = seed_dir / "best_checkpoint"
    seed_dir.mkdir(parents=True, exist_ok=True)

    amp = choose_amp(device)
    print(
        f"\n=== seed={seed} ===\n"
        f"设备：{describe_device(device)} ({device})\n"
        f"混合精度：{amp.name} — {amp.reason}"
    )

    model = load_four_way_model(config.model_id)
    model.to(device)
    assert_ready_to_train(model)
    tokenizer = AutoTokenizer.from_pretrained(config.model_id)
    weights = class_weight_tensor(prepared.class_weight_list)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    scaler = make_grad_scaler(amp, device)

    train_loader = DataLoader(
        PairDataset(list(prepared.train_augmented)),
        batch_size=config.batch_size,
        shuffle=True,
        collate_fn=_collate(tokenizer, config.max_length),
    )
    val_rows = list(prepared.val_rows)
    val_batch = batch_encode(val_rows, tokenizer, max_length=config.max_length)

    max_epochs = 1 if smoke else config.max_epochs
    patience = 1 if smoke else config.early_stop_patience
    history: list[dict[str, Any]] = []
    best_val = float("inf")
    best_epoch = 0
    stale = 0

    for epoch in range(1, max_epochs + 1):
        model.train()
        running = 0.0
        n_batches = 0
        for batch_index, batch in enumerate(train_loader, start=1):
            loss = train_step(
                model,
                batch,
                optimizer,
                class_weights=weights,
                autocast_dtype=amp.dtype,
                scaler=scaler,
            )
            running += loss
            n_batches += 1
            if batch_index % config.log_every_batches == 0:
                print(f"  seed={seed} epoch={epoch} batch={batch_index} loss={loss:.4f}")
            if smoke and batch_index >= 2:
                break

        train_loss = running / max(n_batches, 1)
        val_loss = eval_weighted_loss(model, val_batch, class_weights=weights)
        val_f1 = _val_macro_f1(model, val_rows, tokenizer, config.max_length)
        row = {
            "epoch": epoch,
            "train_loss": train_loss,
            "val_weighted_loss": val_loss,
            "val_macro_f1": val_f1,
        }
        history.append(row)
        print(
            f"epoch {epoch}: train_loss={train_loss:.4f}  "
            f"val_weighted_loss={val_loss:.4f}  val_macro_f1={val_f1:.4f}"
        )

        if val_loss < best_val - 1e-6:
            best_val = val_loss
            best_epoch = epoch
            stale = 0
            if ckpt_dir.exists():
                shutil.rmtree(ckpt_dir)
            ckpt_dir.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(ckpt_dir)
            tokenizer.save_pretrained(ckpt_dir)
            (ckpt_dir / "train_meta.json").write_text(
                json.dumps({"seed": seed, "epoch": epoch, "val_weighted_loss": val_loss}, indent=2),
                encoding="utf-8",
            )
        else:
            stale += 1
            if stale >= patience:
                print(f"早停：验证损失连续 {patience} 轮未刷新最优（最优 epoch={best_epoch}）")
                break

    curve = try_plot_loss_curves(
        history,
        seed_dir / "loss_curve.png",
        best_epoch=best_epoch,
        title=f"seed {seed}",
    )
    (seed_dir / "history.json").write_text(
        json.dumps(
            {
                "seed": seed,
                "best_epoch": best_epoch,
                "best_val_weighted_loss": best_val,
                "amp": amp.name,
                "history": history,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    result = SeedResult(
        seed=seed,
        best_epoch=best_epoch,
        best_val_loss=best_val,
        history=history,
        checkpoint_dir=ckpt_dir,
        curve_path=curve,
    )
    sync_seed_snapshot(run_dir, seed, mirror_dir)
    return result


def _load_four_way_from_dir(path: Path, device: torch.device):
    model = AutoModelForSequenceClassification.from_pretrained(path, dtype=torch.float32)
    model.to(device)
    assert_ready_to_train(model)
    tokenizer = AutoTokenizer.from_pretrained(path)
    return model, tokenizer


def evaluate_all_seeds_on_test(
    *,
    seed_results: list[SeedResult],
    prepared,
    config: TrainConfig,
    device: torch.device,
    run_dir: Path,
) -> dict[str, Any]:
    """测试集只在这里评估一次；选模型仍只看验证损失。"""
    test_rows = list(prepared.test_rows)
    test_no_ident = drop_identical(test_rows)
    base = AutoModelForSequenceClassification.from_pretrained(
        config.model_id, dtype=torch.float32
    )
    base.to(device)
    base_tok = AutoTokenizer.from_pretrained(config.model_id)
    y_true = [str(r["label"]) for r in test_rows]
    y_agree = always_agree_preds(test_rows)
    y_native = base_native_preds(test_rows, base, base_tok, max_length=config.max_length)

    per_seed: list[dict[str, Any]] = []
    for result in seed_results:
        model, tokenizer = _load_four_way_from_dir(result.checkpoint_dir, device)
        y_pred = predict_labels(model, test_rows, tokenizer, max_length=config.max_length)
        y_pred_ni = predict_labels(model, test_no_ident, tokenizer, max_length=config.max_length)
        y_true_ni = [str(r["label"]) for r in test_no_ident]
        report = full_test_report(
            y_true=y_true,
            y_pred=y_pred,
            y_pred_always_agree=y_agree,
            y_pred_base_native=y_native,
            y_true_no_identical=y_true_ni,
            y_pred_no_identical=y_pred_ni,
        )
        entry = {
            "seed": result.seed,
            "best_epoch": result.best_epoch,
            "best_val_weighted_loss": result.best_val_loss,
            "test_macro_f1": report["model"]["macro_f1"],
            "test_accuracy": report["model"]["accuracy"],
            "report": report,
        }
        per_seed.append(entry)
        (run_dir / "seeds" / f"seed_{result.seed}" / "test_report.json").write_text(
            json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    winner = min(seed_results, key=lambda item: (item.best_val_loss, item.seed))
    final_dir = run_dir / "final_model"
    if final_dir.exists():
        shutil.rmtree(final_dir)
    shutil.copytree(winner.checkpoint_dir, final_dir)

    winner_entry = next(item for item in per_seed if item["seed"] == winner.seed)
    f1s = [item["test_macro_f1"] for item in per_seed]
    summary = {
        "selected_seed_by_val_loss": winner.seed,
        "selected_val_weighted_loss": winner.best_val_loss,
        "note": "最终模型只按验证集加权损失选；测试集分数仅用于报告，不参与选型",
        "test_macro_f1_by_seed": {str(item["seed"]): item["test_macro_f1"] for item in per_seed},
        "test_macro_f1_summary": summarize_seed_scores(f1s),
        "winner_test_report": winner_entry["report"],
        "all_seeds": [
            {
                "seed": item["seed"],
                "best_epoch": item["best_epoch"],
                "best_val_weighted_loss": item["best_val_weighted_loss"],
                "test_macro_f1": item["test_macro_f1"],
                "test_accuracy": item["test_accuracy"],
            }
            for item in per_seed
        ],
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "test_report.json").write_text(
        json.dumps(winner_entry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_test_report_md(run_dir / "test_report.md", summary, winner_entry)
    return summary


def _write_test_report_md(path: Path, summary: dict, winner_entry: dict) -> None:
    model = winner_entry["report"]["model"]
    always = winner_entry["report"]["baseline_always_agree"]
    native = winner_entry["report"]["baseline_base_native"]
    no_ident = winner_entry["report"]["model_excluding_identical_pairs"]
    lines = [
        "# 测试集评估报告",
        "",
        f"- 入选种子（仅看验证损失）：**{summary['selected_seed_by_val_loss']}**",
        f"- 三种子测试宏平均 F1：{summary['test_macro_f1_by_seed']}",
        f"- 平均 {summary['test_macro_f1_summary']['mean']:.4f}，"
        f"范围 {summary['test_macro_f1_summary']['min']:.4f}–"
        f"{summary['test_macro_f1_summary']['max']:.4f}"
        f"（波动 {summary['test_macro_f1_summary']['range']:.4f}）",
        "",
        "## 入选模型",
        f"- accuracy: {model['accuracy']:.4f}",
        f"- macro_f1: {model['macro_f1']:.4f}",
        "",
        "## 对照组",
        f"- 永远 agree macro_f1: {always['macro_f1']:.4f}",
        f"- 基座原生格式 macro_f1: {native['macro_f1']:.4f}",
        "",
        "## 去掉完全相同配对之后",
        f"- macro_f1: {no_ident['macro_f1']:.4f}（n={no_ident['n']}）",
        "",
        "## 每类 P/R/F1",
    ]
    for label, scores in model["per_class"].items():
        lines.append(
            f"- {label}: P={scores['precision']:.3f} R={scores['recall']:.3f} "
            f"F1={scores['f1']:.3f} support={int(scores['support'])}"
        )
    lines.extend(
        [
            "",
            "## 混淆矩阵（行=真，列=预测）",
            "```",
            json.dumps(model["confusion_matrix"], indent=2, ensure_ascii=False),
            "```",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _collect_val_logits(model, rows, tokenizer, max_length: int) -> tuple[torch.Tensor, torch.Tensor]:
    from training.labels import LABEL2ID

    model.eval()
    device = next(model.parameters()).device
    logits_chunks: list[torch.Tensor] = []
    label_ids: list[int] = []
    with torch.no_grad():
        for start in range(0, len(rows), 16):
            chunk = rows[start : start + 16]
            batch = batch_encode(chunk, tokenizer, max_length=max_length)
            inputs = {key: value.to(device) for key, value in batch.items() if key != "labels"}
            logits_chunks.append(model(**inputs).logits.detach().float().cpu())
            label_ids.extend(LABEL2ID[str(row["label"])] for row in chunk)
    return stack_logits_labels(logits_chunks, label_ids)


def run_cv(
    config: TrainConfig,
    *,
    n_folds: int,
    allow_cpu: bool = False,
    mirror_dir: Path | None = None,
    calibrate_temperature: bool = False,
) -> Path:
    """分组 K 折 CV：只用 split=train 的题目；测试集完全不碰。"""
    pairs_path = Path(config.pairs_path)
    if not pairs_path.is_file():
        raise FileNotFoundError(pairs_path)
    device = require_gpu(smoke=False, allow_cpu=allow_cpu)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = Path(f"{config.output_dir}-cv{n_folds}-{stamp}")
    run_dir.mkdir(parents=True, exist_ok=True)
    if mirror_dir is not None:
        mirror_dir = Path(mirror_dir)
        mirror_dir.mkdir(parents=True, exist_ok=True)

    all_rows = load_pair_rows(pairs_path)
    train_pool = [row for row in all_rows if row["split"] == "train"]
    folds = grouped_kfold_by_question(train_pool, n_folds=n_folds)
    fold_scores: list[dict[str, Any]] = []
    seed = config.seeds[0]

    print(f"分组 {n_folds} 折 CV（seed={seed}，scheme={config.class_weight_scheme}）")
    print("测试集不参与任何折。")

    for fold in folds:
        print(f"\n----- fold {fold.fold_index + 1}/{n_folds} val={list(fold.val_ids)} -----")
        prepared = prepare_from_pairs(
            pairs_path,
            seed=f"{config.val_split_seed}|fold{fold.fold_index}",
            class_weight_scheme=config.class_weight_scheme,  # type: ignore[arg-type]
            train_ids=fold.train_ids,
            val_ids=fold.val_ids,
        )
        result = train_one_seed(
            config=config,
            prepared=prepared,
            run_dir=run_dir / f"fold_{fold.fold_index}",
            seed=seed,
            device=device,
            smoke=False,
            mirror_dir=None,
        )
        model, tokenizer = _load_four_way_from_dir(result.checkpoint_dir, device)
        val_f1 = _val_macro_f1(model, list(prepared.val_rows), tokenizer, config.max_length)
        entry: dict[str, Any] = {
            "fold": fold.fold_index,
            "val_ids": list(fold.val_ids),
            "best_epoch": result.best_epoch,
            "best_val_weighted_loss": result.best_val_loss,
            "val_macro_f1": val_f1,
        }
        if calibrate_temperature:
            logits, labels = _collect_val_logits(
                model, list(prepared.val_rows), tokenizer, config.max_length
            )
            temperature = fit_temperature(logits, labels)
            entry["calibration"] = calibration_report(logits, labels, temperature=temperature)
            print(
                f"  temperature={temperature:.3f}  "
                f"ECE {entry['calibration']['ece_before']:.4f} → {entry['calibration']['ece_after']:.4f}"
            )
        fold_scores.append(entry)
        print(f"  fold {fold.fold_index} val_macro_f1={val_f1:.4f}")

    f1s = [item["val_macro_f1"] for item in fold_scores]
    summary = {
        "n_folds": n_folds,
        "class_weight_scheme": config.class_weight_scheme,
        "max_epochs": config.max_epochs,
        "patience": config.early_stop_patience,
        "seed": seed,
        "fold_scores": fold_scores,
        "cv_macro_f1_mean": sum(f1s) / len(f1s),
        "cv_macro_f1_std": (sum((x - sum(f1s) / len(f1s)) ** 2 for x in f1s) / len(f1s)) ** 0.5,
        "note": "CV 只在 train 池上按题分组；测试集未使用",
    }
    (run_dir / "cv_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if mirror_dir is not None:
        shutil.copy2(run_dir / "cv_summary.json", mirror_dir / "cv_summary.json")
    print(
        f"\nCV macro-F1 = {summary['cv_macro_f1_mean']:.4f} "
        f"± {summary['cv_macro_f1_std']:.4f}"
    )
    print(f"结果目录：{run_dir.resolve()}")
    return run_dir


def run_training(
    config: TrainConfig,
    *,
    smoke: bool = False,
    allow_cpu: bool = False,
    mirror_dir: Path | None = None,
    calibrate_temperature: bool = False,
    skip_test: bool = False,
) -> Path:
    pairs_path = Path(config.pairs_path)
    if not pairs_path.is_file():
        raise FileNotFoundError(pairs_path)

    device = require_gpu(smoke=smoke, allow_cpu=allow_cpu)
    amp = choose_amp(device)
    print(f"设备：{describe_device(device)}")
    print(f"混合精度：{amp.name} — {amp.reason}")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = Path(
        f"{config.output_dir}-{stamp}" if not smoke else f"{config.output_dir}-smoke-{stamp}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    if mirror_dir is not None:
        mirror_dir = Path(mirror_dir)
        mirror_dir.mkdir(parents=True, exist_ok=True)

    prepared = prepare_from_pairs(
        pairs_path,
        seed=config.val_split_seed,
        class_weight_scheme=config.class_weight_scheme,  # type: ignore[arg-type]
    )
    meta = {
        "config": config_to_dict(config),
        "pairs_sha256": file_sha256(pairs_path),
        "device": str(device),
        "device_name": describe_device(device),
        "amp": {"name": amp.name, "reason": amp.reason},
        "smoke": smoke,
        "split": {
            "train_ids": list(prepared.split.train_ids),
            "val_ids": list(prepared.split.val_ids),
            "test_ids": list(prepared.split.test_ids),
            "reason": prepared.split.reason,
        },
        "counts": prepared.counts_table(),
        "class_weights": prepared.class_weights,
        "class_weight_scheme": prepared.class_weight_scheme,
        "label2id": LABEL2ID,
        "id2label": ID2LABEL,
    }
    (run_dir / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if mirror_dir is not None:
        shutil.copy2(run_dir / "run_meta.json", mirror_dir / "run_meta.json")

    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

    seeds = config.seeds[:1] if smoke else config.seeds
    seed_results = []
    for seed in seeds:
        seed_results.append(
            train_one_seed(
                config=config,
                prepared=prepared,
                run_dir=run_dir,
                seed=seed,
                device=device,
                smoke=smoke,
                mirror_dir=mirror_dir,
            )
        )

    if calibrate_temperature and seed_results:
        winner = min(seed_results, key=lambda item: (item.best_val_loss, item.seed))
        model, tokenizer = _load_four_way_from_dir(winner.checkpoint_dir, device)
        logits, labels = _collect_val_logits(
            model, list(prepared.val_rows), tokenizer, config.max_length
        )
        temperature = fit_temperature(logits, labels)
        calib = calibration_report(logits, labels, temperature=temperature)
        meta["temperature_scaling"] = calib
        (run_dir / "temperature.json").write_text(
            json.dumps(calib, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"temperature={calib['temperature']:.3f}  "
            f"ECE {calib['ece_before']:.4f} → {calib['ece_after']:.4f}"
        )

    if device.type == "cuda":
        peak_mb = torch.cuda.max_memory_allocated(device) / (1024 * 1024)
        print(f"峰值显存：{peak_mb:.0f} MB")
        meta["peak_memory_mb"] = round(peak_mb, 1)
        (run_dir / "run_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if not skip_test and not smoke:
        evaluate_all_seeds_on_test(
            seed_results=seed_results,
            prepared=prepared,
            config=config,
            device=device,
            run_dir=run_dir,
        )
    elif smoke:
        # 冒烟仍走原打包路径所需的最少产物
        evaluate_all_seeds_on_test(
            seed_results=seed_results,
            prepared=prepared,
            config=config,
            device=device,
            run_dir=run_dir,
        )

    pack_dir = run_dir / "package"
    pack_meta = pack_run_artifacts(
        run_dir,
        pack_dir,
        pairs_path=pairs_path,
        max_length=config.max_length,
        device=device,
    )
    meta["package"] = pack_meta
    (run_dir / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    if mirror_dir is not None:
        # 最终整包同步到 Drive
        dest_pack = mirror_dir / "package"
        if dest_pack.exists():
            shutil.rmtree(dest_pack)
        shutil.copytree(pack_dir, dest_pack)
        for name in (
            "summary.json",
            "test_report.json",
            "test_report.md",
            "run_meta.json",
            "temperature.json",
        ):
            src = run_dir / name
            if src.exists():
                shutil.copy2(src, mirror_dir / name)
        print(f"已同步完整结果 → {mirror_dir}")

    print(f"\n结果目录：{run_dir.resolve()}")
    print(f"下载包：{pack_dir.resolve()}（约 {pack_meta['size_mb']} MB）")
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", default=DEFAULT_CONFIG.pairs_path)
    parser.add_argument("--output-dir", default=DEFAULT_CONFIG.output_dir)
    parser.add_argument("--epochs", type=int, default=DEFAULT_CONFIG.max_epochs)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_CONFIG.batch_size)
    parser.add_argument("--lr", type=float, default=DEFAULT_CONFIG.learning_rate)
    parser.add_argument("--max-length", type=int, default=DEFAULT_CONFIG.max_length)
    parser.add_argument("--patience", type=int, default=DEFAULT_CONFIG.early_stop_patience)
    parser.add_argument(
        "--class-weight-scheme",
        choices=("balanced", "sqrt"),
        default=DEFAULT_CONFIG.class_weight_scheme,
        help="balanced=sklearn 公式；sqrt=再开平方缓和稀有类",
    )
    parser.add_argument(
        "--cv",
        type=int,
        default=0,
        help=">0 时跑按题分组 K 折 CV（只用 train 池，不碰测试集）",
    )
    parser.add_argument(
        "--calibrate-temperature",
        action="store_true",
        help="在验证集上拟合 temperature scaling，并报告 ECE 前后",
    )
    parser.add_argument(
        "--seeds",
        default=",".join(str(s) for s in DEFAULT_CONFIG.seeds),
        help="逗号分隔，例如 42,43,44",
    )
    parser.add_argument(
        "--mirror-dir",
        default=None,
        help="每个种子结束后同步到此目录（Colab 上指向 Google Drive）",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="冒烟：1 个种子、1 个 epoch、少量 batch",
    )
    parser.add_argument(
        "--allow-cpu",
        action="store_true",
        help="没有 GPU 时允许用 CPU（仅调试；正式训练不要用）",
    )
    args = parser.parse_args(argv)
    seeds = tuple(int(part.strip()) for part in args.seeds.split(",") if part.strip())
    config = TrainConfig(
        pairs_path=args.pairs,
        output_dir=args.output_dir,
        max_epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        max_length=args.max_length,
        early_stop_patience=args.patience,
        seeds=seeds,
        class_weight_scheme=args.class_weight_scheme,
    )
    mirror = Path(args.mirror_dir) if args.mirror_dir else None
    if args.cv and args.cv > 0:
        if args.smoke:
            raise SystemExit("--cv 与 --smoke 不能一起用")
        run_cv(
            config,
            n_folds=args.cv,
            allow_cpu=args.allow_cpu,
            mirror_dir=mirror,
            calibrate_temperature=args.calibrate_temperature,
        )
        return 0
    run_training(
        config,
        smoke=args.smoke,
        allow_cpu=args.allow_cpu,
        mirror_dir=mirror,
        calibrate_temperature=args.calibrate_temperature,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
