"""分类头 3→4：旧权重保留，新行可区分；训练权重必须是 float32。"""

import pytest
import torch
from torch import nn

from training.labels import LABEL2ID, LABELS
from training.resize_head import (
    assert_trainable_float32,
    resize_classifier,
    training_autocast_dtype,
)


def test_resize_keeps_old_rows_and_adds_scope() -> None:
    old = nn.Linear(8, 3)
    with torch.no_grad():
        old.weight.copy_(torch.arange(24, dtype=torch.float32).reshape(3, 8))
        old.bias.copy_(torch.tensor([10.0, 20.0, 30.0]))

    new = resize_classifier(old, scope_bias=-1.0)

    assert new.out_features == 4
    assert new.in_features == 8
    assert tuple(new.weight.shape) == (4, 8)
    assert new.weight.dtype == torch.float32

    # 旧三类整行原样
    assert torch.equal(new.weight[LABEL2ID["agree"]], old.weight[0])
    assert torch.equal(new.weight[LABEL2ID["unrelated"]], old.weight[1])
    assert torch.equal(new.weight[LABEL2ID["contradict"]], old.weight[2])
    assert new.bias[LABEL2ID["agree"]].item() == 10.0
    assert new.bias[LABEL2ID["unrelated"]].item() == 20.0
    assert new.bias[LABEL2ID["contradict"]].item() == 30.0

    # 新类 = 三行平均，bias = 均值 - 1
    mean_w = old.weight.mean(dim=0)
    assert torch.allclose(new.weight[LABEL2ID["same_question_different_scope"]], mean_w)
    assert new.bias[LABEL2ID["same_question_different_scope"]].item() == 20.0 - 1.0

    assert list(LABELS) == [
        "agree",
        "contradict",
        "same_question_different_scope",
        "unrelated",
    ]


def test_resize_rejects_float16_weights() -> None:
    old = nn.Linear(4, 3, dtype=torch.float16)
    with pytest.raises(TypeError, match="float32"):
        resize_classifier(old)


def test_assert_trainable_float32_rejects_half() -> None:
    model = nn.Linear(4, 2, dtype=torch.float16)
    with pytest.raises(TypeError, match="float32"):
        assert_trainable_float32(model)


def test_assert_trainable_float32_accepts_float32() -> None:
    assert_trainable_float32(nn.Linear(4, 2, dtype=torch.float32))


def test_cpu_autocast_stays_pure_fp32() -> None:
    assert training_autocast_dtype("cpu") is None
