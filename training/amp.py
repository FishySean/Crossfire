"""按显卡选择混合精度。

重要区分（和第 6 步的 fp32 断言不矛盾）：

- 「用 fp16 权重直接训练」= 参数本体存成半精度 → 微小更新会被舍入掉，禁止。
- 「fp16 / bf16 混合精度（autocast）」= 前向/反向计算时用低精度提速，
  参数本体始终是 fp32；GradScaler 防止 fp16 梯度下溢。这是安全的。

选择：
- CUDA + 支持 bf16（Ampere 及以后，如 4090）→ bf16，不用 GradScaler
- CUDA + 不支持 bf16（如 T4）→ fp16 + GradScaler
- CPU → 不用 autocast（纯 fp32）
"""

from __future__ import annotations

from dataclasses import dataclass

import torch


@dataclass(frozen=True)
class AmpChoice:
    dtype: torch.dtype | None
    use_grad_scaler: bool
    name: str
    reason: str


def choose_amp(device: torch.device | str) -> AmpChoice:
    device = torch.device(device)
    if device.type != "cuda" or not torch.cuda.is_available():
        return AmpChoice(
            dtype=None,
            use_grad_scaler=False,
            name="fp32",
            reason="CPU / 无 CUDA：纯 float32，不用 autocast",
        )
    if torch.cuda.is_bf16_supported():
        return AmpChoice(
            dtype=torch.bfloat16,
            use_grad_scaler=False,
            name="bf16",
            reason="本卡支持 bf16（Ampere+）：用 bf16 autocast，参数保持 fp32，无需 GradScaler",
        )
    return AmpChoice(
        dtype=torch.float16,
        use_grad_scaler=True,
        name="fp16+scaler",
        reason=(
            "本卡不支持 bf16（例如 T4）：用 fp16 autocast + GradScaler；"
            "参数仍是 fp32，不是「半精度权重直接训练」"
        ),
    )


def make_grad_scaler(choice: AmpChoice, device: torch.device | str):
    """需要 scaler 时返回 torch.amp.GradScaler；否则返回 None。"""
    if not choice.use_grad_scaler:
        return None
    device = torch.device(device)
    return torch.amp.GradScaler(device.type)


def describe_device(device: torch.device | str) -> str:
    device = torch.device(device)
    if device.type == "cuda" and torch.cuda.is_available():
        return torch.cuda.get_device_name(device)
    return str(device)


# 兼容旧名字：只返回 dtype；新代码请用 choose_amp。
def training_autocast_dtype(device: torch.device | str) -> torch.dtype | None:
    return choose_amp(device).dtype
