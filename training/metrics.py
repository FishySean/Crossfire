"""分类指标：宏平均 F1、每类 P/R/F1、混淆矩阵。不依赖 sklearn。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from training.labels import LABELS


def confusion_matrix(y_true: Sequence[str], y_pred: Sequence[str]) -> dict[str, dict[str, int]]:
    matrix = {gold: {pred: 0 for pred in LABELS} for gold in LABELS}
    for gold, pred in zip(y_true, y_pred, strict=True):
        if gold not in matrix or pred not in matrix[gold]:
            raise ValueError(f"未知标签：true={gold!r} pred={pred!r}")
        matrix[gold][pred] += 1
    return matrix


def per_class_scores(y_true: Sequence[str], y_pred: Sequence[str]) -> dict[str, dict[str, float]]:
    scores: dict[str, dict[str, float]] = {}
    for label in LABELS:
        support = sum(1 for t in y_true if t == label)
        tp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t != label and p == label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / support if support else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        scores[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": float(support),
        }
    return scores


def macro_f1(y_true: Sequence[str], y_pred: Sequence[str]) -> float:
    """只对测试集里出现过的类别取平均（support=0 的类不进宏平均）。"""
    scores = per_class_scores(y_true, y_pred)
    usable = [s["f1"] for s in scores.values() if s["support"] > 0]
    return sum(usable) / len(usable) if usable else 0.0


def accuracy(y_true: Sequence[str], y_pred: Sequence[str]) -> float:
    if not y_true:
        return 0.0
    return sum(t == p for t, p in zip(y_true, y_pred, strict=True)) / len(y_true)


def classification_report(y_true: Sequence[str], y_pred: Sequence[str]) -> dict:
    return {
        "accuracy": accuracy(y_true, y_pred),
        "macro_f1": macro_f1(y_true, y_pred),
        "per_class": per_class_scores(y_true, y_pred),
        "confusion_matrix": confusion_matrix(y_true, y_pred),
        "true_counts": dict(Counter(y_true)),
        "pred_counts": dict(Counter(y_pred)),
        "n": len(y_true),
    }


def summarize_seed_scores(scores: Sequence[float]) -> dict[str, float]:
    if not scores:
        raise ValueError("没有分数可汇总")
    return {
        "mean": sum(scores) / len(scores),
        "min": min(scores),
        "max": max(scores),
        "range": max(scores) - min(scores),
    }
