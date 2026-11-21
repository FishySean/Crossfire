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
) -> list[str]:
    model.eval()
    device = next(model.parameters()).device
    preds: list[str] = []
    with torch.no_grad():
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            batch = batch_encode(chunk, tokenizer, max_length=max_length)
            inputs = {key: value.to(device) for key, value in batch.items() if key != "labels"}
            logits = model(**inputs).logits
            for index in logits.argmax(dim=-1).tolist():
                preds.append(ID2LABEL[int(index)])
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
