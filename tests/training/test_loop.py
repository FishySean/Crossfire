"""训练一步：不下载真实模型，用假 tokenizer + 小线性头。"""

from __future__ import annotations

import torch
from torch import nn

from training.loop import batch_encode, class_weight_tensor, eval_weighted_loss, train_step
from training.labels import LABELS


class _FakeTok:
    def __call__(self, premises, hypotheses, padding=True, truncation=True, max_length=256, return_tensors="pt"):
        n = len(premises)
        return {
            "input_ids": torch.ones(n, 4, dtype=torch.long),
            "attention_mask": torch.ones(n, 4, dtype=torch.long),
        }


class _TinyModel(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.emb = nn.Embedding(10, 8)
        self.classifier = nn.Linear(8, len(LABELS))

    def forward(self, input_ids, attention_mask=None, **kwargs):
        pooled = self.emb(input_ids.clamp(max=9)).mean(dim=1)
        return type("Out", (), {"logits": self.classifier(pooled)})()


def test_train_step_loss_is_finite_and_parameters_move() -> None:
    rows = [
        {
            "question": "q",
            "claim_a": "a1",
            "claim_b": "b1",
            "published_date_a": None,
            "published_date_b": None,
            "label": "agree",
        },
        {
            "question": "q",
            "claim_a": "a2",
            "claim_b": "b2",
            "published_date_a": "2020-01-01",
            "published_date_b": "2021-01-01",
            "label": "contradict",
        },
    ]
    model = _TinyModel()
    before = model.classifier.weight.detach().clone()
    batch = batch_encode(rows, _FakeTok(), max_length=8)
    opt = torch.optim.SGD(model.parameters(), lr=0.1)
    weights = class_weight_tensor([1.0, 1.0, 1.0, 1.0])
    loss = train_step(model, batch, opt, class_weights=weights)
    assert loss == loss  # not NaN
    assert loss > 0
    assert not torch.equal(before, model.classifier.weight.detach())


def test_eval_weighted_loss_does_not_change_weights() -> None:
    rows = [
        {
            "question": "q",
            "claim_a": "a",
            "claim_b": "b",
            "published_date_a": None,
            "published_date_b": None,
            "label": "agree",
        }
    ]
    model = _TinyModel()
    before = {name: param.detach().clone() for name, param in model.named_parameters()}
    batch = batch_encode(rows, _FakeTok(), max_length=8)
    _ = eval_weighted_loss(model, batch, class_weights=class_weight_tensor([1, 1, 1, 1]))
    for name, param in model.named_parameters():
        assert torch.equal(before[name], param.detach())
