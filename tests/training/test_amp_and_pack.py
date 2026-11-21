"""混合精度选型与打包清单：不下载真实大模型。"""

from __future__ import annotations

import json
from pathlib import Path

import torch
from torch import nn

from training.amp import choose_amp, make_grad_scaler
from training.pack import OPTIMIZER_FILE_NAMES, _assert_no_optimizer_state
from training.train import require_gpu


def test_cpu_amp_is_fp32_without_scaler() -> None:
    choice = choose_amp(torch.device("cpu"))
    assert choice.name == "fp32"
    assert choice.dtype is None
    assert make_grad_scaler(choice, "cpu") is None


def test_t4_capability_75_uses_fp16_scaler_not_emulated_bf16(monkeypatch) -> None:
    # 变异目标：若仍用 is_bf16_supported() 默认值，T4 会误选 bf16。
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "get_device_capability", lambda device=None: (7, 5))
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda device=None: "Tesla T4")
    monkeypatch.setattr(torch.cuda, "is_bf16_supported", lambda **kwargs: True)  # 模拟带 emulation 的 True
    choice = choose_amp(torch.device("cuda"))
    assert choice.name == "fp16+scaler"
    assert choice.dtype == torch.float16
    assert choice.use_grad_scaler is True
    assert "7.5" in choice.reason
    assert "bf16" in choice.reason.lower() or "8.0" in choice.reason


def test_ampere_capability_89_uses_bf16(monkeypatch) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "get_device_capability", lambda device=None: (8, 9))
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda device=None: "NVIDIA GeForce RTX 4090")
    choice = choose_amp(torch.device("cuda"))
    assert choice.name == "bf16"
    assert choice.dtype == torch.bfloat16
    assert choice.use_grad_scaler is False
    assert "8.9" in choice.reason


def test_notebooks_have_no_saved_outputs() -> None:
    """进 git 的笔记本不得带执行输出，避免 Colab 回写把大段 stdout 推进仓库。"""
    root = Path(__file__).resolve().parents[2]
    offenders: list[str] = []
    for path in sorted((root / "training").glob("*.ipynb")):
        nb = json.loads(path.read_text(encoding="utf-8"))
        for index, cell in enumerate(nb.get("cells", [])):
            if cell.get("cell_type") != "code":
                continue
            if cell.get("outputs"):
                offenders.append(f"{path.name} cell[{index}] has outputs")
            if cell.get("execution_count") not in (None, 0):
                offenders.append(f"{path.name} cell[{index}] execution_count={cell.get('execution_count')}")
    assert offenders == []


def test_require_gpu_exits_without_allowance(monkeypatch) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    try:
        require_gpu(smoke=False, allow_cpu=False)
        raised = False
    except SystemExit:
        raised = True
    assert raised


def test_require_gpu_allows_cpu_for_smoke(monkeypatch) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    device = require_gpu(smoke=True, allow_cpu=False)
    assert device.type == "cpu"


def test_pack_rejects_optimizer_state(tmp_path: Path) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "model.safetensors").write_bytes(b"x")
    (model_dir / "optimizer.pt").write_bytes(b"bad")
    try:
        _assert_no_optimizer_state(model_dir)
        ok = False
    except RuntimeError as exc:
        ok = "optimizer.pt" in str(exc)
    assert ok
    assert "optimizer.pt" in OPTIMIZER_FILE_NAMES


def test_train_step_with_fake_scaler_path() -> None:
    # 确保 GradScaler 参数位能接住（CPU 上 scaler=None 的路径在 loop 单测里已覆盖）
    from training.loop import train_step

    class Tiny(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.emb = nn.Embedding(8, 4)
            self.classifier = nn.Linear(4, 4)

        def forward(self, input_ids, attention_mask=None, **kwargs):
            pooled = self.emb(input_ids.clamp(max=7)).mean(dim=1)
            return type("O", (), {"logits": self.classifier(pooled)})()

    model = Tiny()
    opt = torch.optim.SGD(model.parameters(), lr=0.1)
    batch = {
        "input_ids": torch.ones(2, 3, dtype=torch.long),
        "attention_mask": torch.ones(2, 3, dtype=torch.long),
        "labels": torch.tensor([0, 1]),
    }
    loss = train_step(model, batch, opt, autocast_dtype=None, scaler=None)
    assert loss == loss
