"""按显卡选择混合精度。

重要区分（和第 6 步的 fp32 断言不矛盾）：

- 「用 fp16 权重直接训练」= 参数本体存成半精度 → 微小更新会被舍入掉，禁止。
- 「fp16 / bf16 混合精度（autocast）」= 前向/反向计算时用低精度提速，
  参数本体始终是 fp32；GradScaler 防止 fp16 梯度下溢。这是安全的。

选择（按硬件算力版本，不用 is_bf16_supported 的默认值）：
- CUDA + 算力主版本 ≥ 8（Ampere+，如 4090）→ bf16，不用 GradScaler
- CUDA + 算力主版本 < 8（如 T4=7.5）→ fp16 + GradScaler
- CPU → 不用 autocast（纯 fp32）

为什么不用 torch.cuda.is_bf16_supported() 的默认调用：
新版 torch 默认 including_emulation=True，T4 虽无硬件 bf16，但软件模拟也会返回 True，
训练会走模拟路径、用不上 Tensor Core，明显变慢。按 get_device_capability() 判断更直接。
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


def hardware_bf16_ok(device: torch.device | str) -> bool:
    """硬件原生 bf16：算力主版本 ≥ 8（Ampere 及以后）。"""
    device = torch.device(device)
    if device.type != "cuda" or not torch.cuda.is_available():
        return False
    major, _minor = torch.cuda.get_device_capability(device)
    return major >= 8


def choose_amp(device: torch.device | str) -> AmpChoice:
    device = torch.device(device)
    if device.type != "cuda" or not torch.cuda.is_available():
        return AmpChoice(
            dtype=None,
            use_grad_scaler=False,
            name="fp32",
            reason="CPU / 无 CUDA：纯 float32，不用 autocast",
        )

    major, minor = torch.cuda.get_device_capability(device)
    if major >= 8:
        return AmpChoice(
            dtype=torch.bfloat16,
            use_grad_scaler=False,
            name="bf16",
            reason=(
                f"算力 {major}.{minor}≥8.0（Ampere+）：硬件原生 bf16，"
                "用 bf16 autocast，参数保持 fp32，无需 GradScaler"
            ),
        )
    return AmpChoice(
        dtype=torch.float16,
        use_grad_scaler=True,
        name="fp16+scaler",
        reason=(
            f"算力 {major}.{minor}<8.0（例如 T4=7.5）：无硬件 bf16"
            "（忽略 is_bf16_supported 的软件模拟），"
            "用 fp16 autocast + GradScaler；参数仍是 fp32"
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
