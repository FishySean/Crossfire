"""把每个 epoch 的训练/验证损失画成 PNG，并标出早停选中的那一轮。

只用非交互后端 Agg：Colab 会设 MPLBACKEND=module://matplotlib_inline...，
uv 子进程继承后若没装 matplotlib_inline 会在 import 时直接炸。
训练只需要存文件，不需要弹窗显示。
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path


def _force_agg_backend() -> None:
    # 必须在 import pyplot 之前；force=True 覆盖环境变量里的无效后端
    os.environ["MPLBACKEND"] = "Agg"
    import matplotlib

    matplotlib.use("Agg", force=True)


def plot_loss_curves(
    history: Sequence[dict],
    out_path: Path,
    *,
    best_epoch: int,
    title: str = "train / val loss",
) -> Path:
    """history 每项需含 epoch, train_loss, val_weighted_loss。成功返回 PNG 路径。"""
    if not history:
        raise ValueError("history 为空，无法画图")

    _force_agg_backend()
    import matplotlib.pyplot as plt

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


def try_plot_loss_curves(
    history: Sequence[dict],
    out_path: Path,
    *,
    best_epoch: int,
    title: str = "train / val loss",
) -> Path | None:
    """画图失败只警告，不抛错——训练和存盘继续。"""
    try:
        return plot_loss_curves(history, out_path, best_epoch=best_epoch, title=title)
    except Exception as exc:  # noqa: BLE001 — 有意兜住后端/缺依赖等，避免白训
        print(f"警告：损失曲线未能写出（{out_path}）：{exc}")
        print("模型和 history.json 仍会保存；可稍后本机重画。")
        return None
