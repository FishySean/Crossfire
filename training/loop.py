"""最小训练循环：编码 → 前向 → 加权交叉熵 → 反向。

第 8 步过拟合检查和第 9 步完整训练共用这里，避免两套损失计算。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import torch
from torch import nn
from transformers import PreTrainedTokenizerBase

from crossfire.adapters.nli.encoding import encode_pair_row
from training.early_stop import EARLY_STOP_METRIC
from training.labels import LABEL2ID, LABELS


def assert_ready_to_train(model: nn.Module) -> None:
    from training.resize_head import assert_trainable_float32

    assert_trainable_float32(model)


def batch_encode(
    rows: Sequence[Mapping[str, Any]],
    tokenizer: PreTrainedTokenizerBase,
    *,
    max_length: int = 160,
) -> dict[str, torch.Tensor]:
    premises: list[str] = []
    hypotheses: list[str] = []
    labels: list[int] = []
    for row in rows:
        enc = encode_pair_row(row)
        premises.append(enc.premise)
        hypotheses.append(enc.hypothesis)
        labels.append(LABEL2ID[str(row["label"])])
    encoded = tokenizer(
        premises,
        hypotheses,
        padding=True,
        truncation=True,
        max_length=max_length,
        return_tensors="pt",
    )
    encoded["labels"] = torch.tensor(labels, dtype=torch.long)
    return encoded


def weighted_ce_loss(
    logits: torch.Tensor,
    labels: torch.Tensor,
    class_weights: torch.Tensor | None,
) -> torch.Tensor:
    return nn.functional.cross_entropy(logits, labels, weight=class_weights)


def train_step(
    model: nn.Module,
    batch: Mapping[str, torch.Tensor],
    optimizer: torch.optim.Optimizer,
    *,
    class_weights: torch.Tensor | None = None,
    autocast_dtype: torch.dtype | None = None,
    scaler: torch.amp.GradScaler | None = None,
) -> float:
    """一步：清梯度 → 前向 → 加权损失 → 反向 → 更新。返回标量 loss。

    scaler 只在 fp16 混合精度时使用。参数本体始终是 fp32。
    """
    model.train()
    optimizer.zero_grad(set_to_none=True)
    device = next(model.parameters()).device
    batch = {key: value.to(device) for key, value in batch.items()}
    labels = batch["labels"]
    inputs = {key: value for key, value in batch.items() if key != "labels"}
    weights = None if class_weights is None else class_weights.to(device=device, dtype=torch.float32)

    if autocast_dtype is None:
        logits = model(**inputs).logits
        loss = weighted_ce_loss(logits, labels, weights)
        loss.backward()
        optimizer.step()
    else:
        with torch.autocast(device_type=device.type, dtype=autocast_dtype):
            logits = model(**inputs).logits
            loss = weighted_ce_loss(logits, labels, weights)
        if scaler is None:
            loss.backward()
            optimizer.step()
        else:
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()

    return float(loss.detach().float().cpu())


def eval_weighted_loss(
    model: nn.Module,
    batch: Mapping[str, torch.Tensor],
    *,
    class_weights: torch.Tensor | None = None,
) -> float:
    """验证集用的加权损失（EARLY_STOP_METRIC）。不更新参数。"""
    assert EARLY_STOP_METRIC == "val_weighted_loss"
    model.eval()
    device = next(model.parameters()).device
    batch = {key: value.to(device) for key, value in batch.items()}
    labels = batch["labels"]
    inputs = {key: value for key, value in batch.items() if key != "labels"}
    weights = None if class_weights is None else class_weights.to(device=device, dtype=torch.float32)
    with torch.no_grad():
        logits = model(**inputs).logits
        loss = weighted_ce_loss(logits, labels, weights)
    return float(loss.float().cpu())


def class_weight_tensor(weight_list: Sequence[float]) -> torch.Tensor:
    if len(weight_list) != len(LABELS):
        raise ValueError(f"期望 {len(LABELS)} 个权重，实际 {len(weight_list)}")
    return torch.tensor(list(weight_list), dtype=torch.float32)
