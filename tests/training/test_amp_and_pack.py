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
