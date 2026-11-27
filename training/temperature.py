"""Temperature scaling：只校准置信度，不改 argmax 类别。

在验证集 logits 上拟合标量 T，使 NLL 最小；报告校准前后 ECE。
"""

from __future__ import annotations

from collections.abc import Sequence

import torch
import torch.nn.functional as F


def expected_calibration_error(
    probs: torch.Tensor,
    labels: torch.Tensor,
    *,
    n_bins: int = 15,
) -> float:
    """多分类 ECE：按 max-prob 分箱，|acc - conf| 加权平均。"""
    if probs.ndim != 2 or labels.ndim != 1 or probs.size(0) != labels.size(0):
        raise ValueError("probs 形状应为 [N,C]，labels 为 [N]")
    confidences, predictions = probs.max(dim=1)
    accuracies = predictions.eq(labels).float()
    ece = torch.zeros((), device=probs.device)
    for bin_index in range(n_bins):
        lo = bin_index / n_bins
        hi = (bin_index + 1) / n_bins
        mask = (confidences > lo) & (confidences <= hi)
        if not bool(mask.any()):
            continue
        ece = ece + mask.float().mean() * (accuracies[mask].mean() - confidences[mask].mean()).abs()
    return float(ece.item())


def fit_temperature(
    logits: torch.Tensor,
    labels: torch.Tensor,
    *,
    max_iter: int = 50,
    lr: float = 0.01,
) -> float:
    """在验证 logits 上拟合 temperature（>0）。返回 T。"""
    if logits.ndim != 2 or labels.ndim != 1:
        raise ValueError("logits/labels 形状不对")
    # log T 无约束优化，保证 T>0
    log_t = torch.nn.Parameter(torch.zeros((), device=logits.device, dtype=torch.float32))
    optimizer = torch.optim.LBFGS([log_t], lr=lr, max_iter=max_iter)

    def closure() -> torch.Tensor:
        optimizer.zero_grad()
        temperature = log_t.exp().clamp_min(1e-3)
        loss = F.cross_entropy(logits / temperature, labels)
        loss.backward()
        return loss

    optimizer.step(closure)
    return float(log_t.exp().clamp_min(1e-3).item())


def apply_temperature(logits: torch.Tensor, temperature: float) -> torch.Tensor:
    return logits / max(float(temperature), 1e-3)


def calibration_report(
    logits: torch.Tensor,
    labels: torch.Tensor,
    *,
    temperature: float,
    n_bins: int = 15,
) -> dict[str, float]:
    before = F.softmax(logits, dim=-1)
    after = F.softmax(apply_temperature(logits, temperature), dim=-1)
    return {
        "temperature": float(temperature),
        "ece_before": expected_calibration_error(before, labels, n_bins=n_bins),
        "ece_after": expected_calibration_error(after, labels, n_bins=n_bins),
        "n": int(labels.size(0)),
    }


def stack_logits_labels(
    logits_list: Sequence[torch.Tensor],
    label_ids: Sequence[int],
) -> tuple[torch.Tensor, torch.Tensor]:
    logits = torch.cat([t.detach().float().cpu() for t in logits_list], dim=0)
    labels = torch.tensor(list(label_ids), dtype=torch.long)
    return logits, labels
