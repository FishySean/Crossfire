"""按训练集（增强后）各类数量算类别权重。

公式（sklearn balanced）：weight_c = N / (K * n_c)
- N：样例总数
- K：类别数（这里是 4）
- n_c：类别 c 的条数

稀有类权重大 → 判错时罚得更重，避免模型永远猜「一致」。
权重基于增强后的训练集；验证/测试不参与计算。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from training.labels import LABELS


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


def class_weight_tensor_values(weights: Mapping[str, float]) -> list[float]:
    """按 LABELS 顺序排成 list，方便直接塞进 CrossEntropyLoss。"""
    return [float(weights[label]) for label in LABELS]
