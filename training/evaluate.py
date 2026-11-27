"""在给定行上跑模型，产出完整评估报告（含对照组与去相同配对）。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import torch
from torch import nn
from transformers import PreTrainedTokenizerBase

from training.labels import ID2LABEL, LABELS
from training.loop import batch_encode
from training.metrics import classification_report


def predict_labels(
    model: nn.Module,
    rows: Sequence[Mapping[str, Any]],
    tokenizer: PreTrainedTokenizerBase,
    *,
    max_length: int = 160,
    batch_size: int = 16,
    mask_unrelated: bool = False,
) -> list[str]:
    from crossfire.adapters.nli.mask import mask_unrelated_logits

    model.eval()
    device = next(model.parameters()).device
    id2label = {int(k): str(v) for k, v in getattr(model.config, "id2label", ID2LABEL).items()}
    # 训练脚本里的头可能用 int 键；统一成 dict[int,str]
    if not id2label:
        id2label = dict(ID2LABEL)
    preds: list[str] = []
    with torch.no_grad():
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            batch = batch_encode(chunk, tokenizer, max_length=max_length)
            inputs = {key: value.to(device) for key, value in batch.items() if key != "labels"}
            logits = model(**inputs).logits
            logits = mask_unrelated_logits(logits, id2label, enabled=mask_unrelated)
            for index in logits.argmax(dim=-1).tolist():
                preds.append(id2label[int(index)])
    return preds


def always_agree_preds(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    return ["agree"] * len(rows)


def base_native_preds(
    rows: Sequence[Mapping[str, Any]],
    base_model: nn.Module,
    tokenizer: PreTrainedTokenizerBase,
    *,
    max_length: int = 160,
    batch_size: int = 16,
) -> list[str]:
    """不训练直接用：只喂两句主张（原生 NLI 格式），映射到我们的四类（无 scope）。"""
    from unicodedata import normalize

    map3 = {"entailment": "agree", "contradiction": "contradict", "neutral": "unrelated"}
    base_model.eval()
    device = next(base_model.parameters()).device
    preds: list[str] = []
    with torch.no_grad():
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            a = [normalize("NFKC", str(r["claim_a"]).strip()) for r in chunk]
            b = [normalize("NFKC", str(r["claim_b"]).strip()) for r in chunk]
            encoded = tokenizer(
                a, b, padding=True, truncation=True, max_length=max_length, return_tensors="pt"
            )
            encoded = {key: value.to(device) for key, value in encoded.items()}
            logits = base_model(**encoded).logits
            id2label = {int(k): v for k, v in base_model.config.id2label.items()}
            for index in logits.argmax(dim=-1).tolist():
                preds.append(map3[id2label[int(index)]])
    return preds


def drop_identical(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if str(row["claim_a"]).strip() != str(row["claim_b"]).strip()
    ]


def full_test_report(
    *,
    y_true: Sequence[str],
    y_pred: Sequence[str],
    y_pred_always_agree: Sequence[str],
    y_pred_base_native: Sequence[str],
    y_true_no_identical: Sequence[str],
    y_pred_no_identical: Sequence[str],
) -> dict[str, Any]:
    return {
        "labels": list(LABELS),
        "model": classification_report(y_true, y_pred),
        "baseline_always_agree": classification_report(y_true, y_pred_always_agree),
        "baseline_base_native": classification_report(y_true, y_pred_base_native),
        "model_excluding_identical_pairs": classification_report(
            y_true_no_identical, y_pred_no_identical
        ),
        "n_identical_in_eval": len(y_true) - len(y_true_no_identical),
    }


def _rows_for_split(pairs_path: str | Path, split: str) -> list[dict[str, Any]]:
    from training.prepare import prepare_from_pairs

    prepared = prepare_from_pairs(pairs_path)
    if split == "test":
        return list(prepared.test_rows)
    if split == "val":
        return list(prepared.val_rows)
    if split == "train":
        return list(prepared.train_rows)
    raise ValueError(f"未知 split：{split}")


def flip_stats(
    y_true: Sequence[str],
    y_pred_off: Sequence[str],
    y_pred_on: Sequence[str],
) -> dict[str, Any]:
    """统计屏蔽前后相对金标的正确→错误 / 错误→正确 / 仍错但改类。"""
    correct_to_wrong: list[dict[str, str]] = []
    wrong_to_correct: list[dict[str, str]] = []
    wrong_to_wrong_changed: list[dict[str, str]] = []
    for index, (gold, off, on) in enumerate(zip(y_true, y_pred_off, y_pred_on, strict=True)):
        if off == on:
            continue
        entry = {"index": str(index), "gold": gold, "off": off, "on": on}
        off_ok = off == gold
        on_ok = on == gold
        if off_ok and not on_ok:
            correct_to_wrong.append(entry)
        elif (not off_ok) and on_ok:
            wrong_to_correct.append(entry)
        else:
            wrong_to_wrong_changed.append(entry)
    return {
        "correct_to_wrong": len(correct_to_wrong),
        "wrong_to_correct": len(wrong_to_correct),
        "wrong_to_wrong_changed": len(wrong_to_wrong_changed),
        "correct_to_wrong_pairs": correct_to_wrong,
        "wrong_to_correct_pairs": wrong_to_correct,
        "wrong_to_wrong_changed_pairs": wrong_to_wrong_changed,
    }


def evaluate_checkpoint(
    model_dir: str | Path,
    pairs_path: str | Path,
    *,
    split: str = "test",
    mask_unrelated: bool = False,
    max_length: int = 160,
) -> dict[str, Any]:
    """对本地 checkpoint 重新推理（不训练）。split=val 时用 prepare 切出的验证题。"""
    from pathlib import Path as _Path

    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    rows = _rows_for_split(pairs_path, split)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = AutoModelForSequenceClassification.from_pretrained(
        _Path(model_dir), dtype=torch.float32
    )
    model.to(device)
    tokenizer = AutoTokenizer.from_pretrained(_Path(model_dir))
    y_true = [str(row["label"]) for row in rows]
    y_pred = predict_labels(
        model, rows, tokenizer, max_length=max_length, mask_unrelated=mask_unrelated
    )
    report = classification_report(y_true, y_pred)
    unrelated_pred = sum(1 for p in y_pred if p == "unrelated")
    return {
        "model_dir": str(model_dir),
        "split": split,
        "n": len(rows),
        "mask_unrelated": mask_unrelated,
        "unrelated_predictions": unrelated_pred,
        "report": report,
    }


def compare_mask_checkpoint(
    model_dir: str | Path,
    pairs_path: str | Path,
    *,
    split: str = "test",
    max_length: int = 160,
) -> dict[str, Any]:
    """同一次加载，对比屏蔽开/关，并统计正确→错误等翻转。"""
    from pathlib import Path as _Path

    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    rows = _rows_for_split(pairs_path, split)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = AutoModelForSequenceClassification.from_pretrained(
        _Path(model_dir), dtype=torch.float32
    )
    model.to(device)
    tokenizer = AutoTokenizer.from_pretrained(_Path(model_dir))
    y_true = [str(row["label"]) for row in rows]
    y_off = predict_labels(
        model, rows, tokenizer, max_length=max_length, mask_unrelated=False
    )
    y_on = predict_labels(
        model, rows, tokenizer, max_length=max_length, mask_unrelated=True
    )
    flips = flip_stats(y_true, y_off, y_on)
    off_report = classification_report(y_true, y_off)
    on_report = classification_report(y_true, y_on)
    return {
        "model_dir": str(model_dir),
        "split": split,
        "n": len(rows),
        "off": {
            "mask_unrelated": False,
            "unrelated_predictions": sum(1 for p in y_off if p == "unrelated"),
            "report": off_report,
        },
        "on": {
            "mask_unrelated": True,
            "unrelated_predictions": sum(1 for p in y_on if p == "unrelated"),
            "report": on_report,
        },
        "flips": flips,
        "gate_correct_to_wrong_zero": flips["correct_to_wrong"] == 0,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="对 checkpoint 重新推理评估（可开/关屏蔽 unrelated）")
    parser.add_argument("--model-dir", required=True, help="本地模型目录（含 config.json + 权重）")
    parser.add_argument("--pairs", default="data/pairs.jsonl")
    parser.add_argument("--split", choices=("test", "val", "train"), default="test")
    parser.add_argument(
        "--mask-unrelated",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="推理时屏蔽 unrelated（默认关；评估脚本显式开关便于对比）",
    )
    parser.add_argument(
        "--compare-mask",
        action="store_true",
        help="同一次加载对比开/关，并统计正确→错误 / 错误→正确",
    )
    parser.add_argument("--max-length", type=int, default=160)
    parser.add_argument("--out", type=Path, default=None, help="把 JSON 报告写到此路径")
    args = parser.parse_args(argv)
    if args.compare_mask:
        result = compare_mask_checkpoint(
            args.model_dir,
            args.pairs,
            split=args.split,
            max_length=args.max_length,
        )
    else:
        result = evaluate_checkpoint(
            args.model_dir,
            args.pairs,
            split=args.split,
            mask_unrelated=args.mask_unrelated,
            max_length=args.max_length,
        )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
