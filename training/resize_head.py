"""把基座三分类头扩成四分类头。

基座学过：entailment / neutral / contradiction。
我们要判：agree / contradict / same_question_different_scope / unrelated。

策略：三个旧类整行拷贝对应权重；新类「口径不同」用三行平均初始化，
再把 bias 略压低一点，避免一上来就抢过旧类。

加载一律强制 float32：checkpoint 虽是 fp16 存盘，直接拿 fp16 权重训练会
把微小梯度舍入掉（损失不降且不报错）或溢出成 NaN。GPU 上再用 bf16 autocast
提速，参数本体始终保持 fp32。
"""

from __future__ import annotations

import torch
from torch import nn
from transformers import AutoConfig, AutoModelForSequenceClassification

from training.labels import BASE_ROW_FOR_LABEL, ID2LABEL, LABEL2ID, LABELS

BASE_MODEL_ID = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"


def assert_trainable_float32(model: nn.Module) -> None:
    """训练开始前：所有可训练参数必须是 float32，否则立刻停下。"""
    bad = [
        (name, tuple(param.shape), str(param.dtype))
        for name, param in model.named_parameters()
        if param.requires_grad and param.dtype != torch.float32
    ]
    if bad:
        sample = ", ".join(f"{n} {shape} {dtype}" for n, shape, dtype in bad[:5])
        raise TypeError(
            f"可训练参数必须是 float32，发现 {len(bad)} 个不是（例如：{sample}）。"
            "请用 dtype=torch.float32 加载，不要用 checkpoint 里的 float16。"
        )


def resize_classifier(old: nn.Linear, *, scope_bias: float = -1.0) -> nn.Linear:
    """3→4：旧行按映射拷贝；新行 = 旧三行平均，bias 再减一点。"""
    if old.out_features != 3:
        raise ValueError(f"期望基座是 3 类，实际 out_features={old.out_features}")
    if old.weight.dtype != torch.float32:
        raise TypeError(
            f"分类头扩容要求 float32 权重，实际 dtype={old.weight.dtype}。"
            "先把模型转成 float32 再调用。"
        )

    new = nn.Linear(old.in_features, len(LABELS), device=old.weight.device, dtype=torch.float32)
    with torch.no_grad():
        mean_w = old.weight.mean(dim=0)
        mean_b = float(old.bias.mean())
        for label, new_row in LABEL2ID.items():
            if label in BASE_ROW_FOR_LABEL:
                src = BASE_ROW_FOR_LABEL[label]
                new.weight[new_row].copy_(old.weight[src])
                new.bias[new_row].copy_(old.bias[src])
            else:
                # same_question_different_scope：没有旧行可抄
                new.weight[new_row].copy_(mean_w)
                new.bias[new_row].fill_(mean_b + scope_bias)
    return new


def load_four_way_model(model_id: str = BASE_MODEL_ID):
    """加载基座（强制 float32），换四分类头，并改写 config 的标签表。"""
    config = AutoConfig.from_pretrained(model_id)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_id,
        config=config,
        dtype=torch.float32,  # 覆盖 checkpoint 的 float16；参数必须能记下微小更新
    )
    model.classifier = resize_classifier(model.classifier)
    model.config.num_labels = len(LABELS)
    model.config.id2label = {int(k): v for k, v in ID2LABEL.items()}
    model.config.label2id = dict(LABEL2ID)
    model.num_labels = len(LABELS)
    assert_trainable_float32(model)
    return model


def training_autocast_dtype(device: torch.device | str) -> torch.dtype | None:
    """GPU 用 bf16 混合精度；CPU 返回 None（纯 fp32，不用 autocast）。"""
    device = torch.device(device)
    if device.type == "cuda" and torch.cuda.is_available() and torch.cuda.is_bf16_supported():
        return torch.bfloat16
    return None


def head_summary(model) -> dict[str, object]:
    """给人看的摘要：形状、标签、新行怎么来的。"""
    weight = model.classifier.weight
    return {
        "num_labels": int(model.config.num_labels),
        "weight_shape": tuple(weight.shape),
        "bias_shape": tuple(model.classifier.bias.shape),
        "weight_dtype": str(weight.dtype),
        "id2label": dict(model.config.id2label),
        "init": {
            "agree": "拷贝基座 entailment（行 0）",
            "contradict": "拷贝基座 contradiction（行 2）",
            "unrelated": "拷贝基座 neutral（行 1）",
            "same_question_different_scope": "三行权重平均 + bias 再 -1.0",
        },
        "labels": list(LABELS),
    }
