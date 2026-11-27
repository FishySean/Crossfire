"""按训练集（增强后）各类数量算类别权重。

公式（sklearn balanced）：weight_c = N / (K * n_c)
- N：样例总数
- K：类别数（这里是 4）
- n_c：类别 c 的条数

稀有类权重大 → 判错时罚得更重，避免模型永远猜「一致」。
权重基于增强后的训练集；验证/测试不参与计算。

`--class-weight-scheme sqrt`：对 balanced 权重再开平方，缓和 unrelated 等极稀有类的过重惩罚。
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from training.labels import LABELS

WeightScheme = Literal["balanced", "sqrt"]


def balanced_class_weights(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    counts = Counter(str(row["label"]) for row in rows)
    missing = [label for label in LABELS if counts.get(label, 0) == 0]
    if missing:
        raise ValueError(f"训练集缺少类别，无法算权重：{missing}")

    total = sum(counts[label] for label in LABELS)
    n_classes = len(LABELS)
    return {
        label: total / (n_classes * counts[label])
        for label in LABELS
    }


def sqrt_class_weights(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """balanced 后再开平方并重新归一化到均值 1，减轻极端稀有类权重。"""
    base = balanced_class_weights(rows)
    rooted = {label: math.sqrt(weight) for label, weight in base.items()}
    mean = sum(rooted.values()) / len(rooted)
    if mean <= 0:
        raise ValueError("平方根权重均值异常")
    return {label: weight / mean for label, weight in rooted.items()}


def class_weights_for_scheme(
    rows: Sequence[Mapping[str, Any]],
    scheme: WeightScheme = "balanced",
) -> dict[str, float]:
    if scheme == "balanced":
        return balanced_class_weights(rows)
    if scheme == "sqrt":
        return sqrt_class_weights(rows)
    raise ValueError(f"未知 class-weight-scheme：{scheme!r}（可选 balanced / sqrt）")


def class_weight_tensor_values(weights: Mapping[str, float]) -> list[float]:
    """按 LABELS 顺序排成 list，方便直接塞进 CrossEntropyLoss。"""
    return [float(weights[label]) for label in LABELS]
