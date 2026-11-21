"""把每个 epoch 的训练/验证损失画成 PNG，并标出早停选中的那一轮。"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


def plot_loss_curves(
    history: Sequence[dict],
    out_path: Path,
    *,
    best_epoch: int,
    title: str = "train / val loss",
) -> Path:
    """history 每项需含 epoch, train_loss, val_weighted_loss。"""
    import matplotlib.pyplot as plt

    if not history:
        raise ValueError("history 为空，无法画图")

    epochs = [int(row["epoch"]) for row in history]
    train = [float(row["train_loss"]) for row in history]
    val = [float(row["val_weighted_loss"]) for row in history]

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(epochs, train, marker="o", label="train_loss")
    ax.plot(epochs, val, marker="o", label="val_weighted_loss")
    ax.axvline(best_epoch, color="gray", linestyle="--", label=f"early stop @ {best_epoch}")
    ax.set_xlabel("epoch")
    ax.set_ylabel("loss")
    ax.set_title(title)
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path
