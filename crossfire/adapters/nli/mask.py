"""推理时屏蔽 unrelated：按系统设计，同一问题下的主张对不应判为 unrelated。

只改推理 logits，不改模型权重、不改标签体系。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

UNRELATED_LABEL = "unrelated"


def unrelated_class_index(id2label: Mapping[int, str]) -> int | None:
    for index, name in id2label.items():
        if str(name) == UNRELATED_LABEL:
            return int(index)
    return None


def mask_unrelated_logits(
    logits: Any,
    id2label: Mapping[int, str],
    *,
    enabled: bool = True,
) -> Any:
    """把 unrelated 维设为 -inf；enabled=False 时原样返回。

    logits：形状 [N, C] 的 torch.Tensor（或测试用的假张量，需支持 clone 与 [:, i] 赋值）。
    """
    if not enabled:
        return logits
    index = unrelated_class_index(id2label)
    if index is None:
        return logits
    masked = logits.clone()
    masked[:, index] = float("-inf")
    return masked
