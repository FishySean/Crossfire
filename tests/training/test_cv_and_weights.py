"""第 10 步：分组 CV 与平方根类别权重。"""

from __future__ import annotations

import math

import pytest
import torch

from training.class_weights import balanced_class_weights, class_weights_for_scheme, sqrt_class_weights
from training.cv import grouped_kfold_by_question
from training.temperature import expected_calibration_error, fit_temperature


def _row(qid: str, label: str) -> dict:
    return {
        "question_id": qid,
        "label": label,
        "claim_a": f"{qid}-a",
        "claim_b": f"{qid}-b",
        "split": "train",
    }


def test_grouped_kfold_keeps_questions_intact() -> None:
    rows = []
    for qid in [f"q{i}" for i in range(10)]:
        rows.append(_row(qid, "agree"))
        rows.append(_row(qid, "contradict"))
    folds = grouped_kfold_by_question(rows, n_folds=5, seed="unit")
    assert len(folds) == 5
    all_val = [qid for fold in folds for qid in fold.val_ids]
    assert len(all_val) == len(set(all_val)) == 10
    for fold in folds:
        assert set(fold.train_ids).isdisjoint(fold.val_ids)
        # 同一题不能同时出现在 train 与 val
        for qid in fold.val_ids:
            assert qid not in fold.train_ids


def test_sqrt_weights_less_extreme_than_balanced() -> None:
    rows = (
        [_row("q", "agree") for _ in range(20)]
        + [_row("q", "contradict") for _ in range(2)]
        + [_row("q", "same_question_different_scope")]
        + [_row("q", "unrelated")]
    )
    bal = balanced_class_weights(rows)
    sqrt = sqrt_class_weights(rows)
    assert sqrt["unrelated"] < bal["unrelated"]
    assert math.isclose(sum(sqrt.values()) / len(sqrt), 1.0, rel_tol=1e-6)
    assert class_weights_for_scheme(rows, "sqrt") == sqrt


def test_temperature_fit_returns_positive_scalar() -> None:
    logits = torch.eye(4) * 3.0
    labels = torch.arange(4)
    temperature = fit_temperature(logits, labels, max_iter=20)
    assert temperature > 0
    # 完美校准数据上 ECE 应接近 0
    ece = expected_calibration_error(torch.softmax(logits / temperature, dim=-1), labels)
    assert ece < 0.5


def test_unknown_scheme_raises() -> None:
    with pytest.raises(ValueError, match="未知"):
        class_weights_for_scheme([_row("q", "agree")], "nope")  # type: ignore[arg-type]
