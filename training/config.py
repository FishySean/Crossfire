"""正式训练的默认超参数。每个数字旁边写了为什么这么选。

默认面向 Google Colab T4；在 RunPod 4090 上同样适用（会自动选 bf16）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class TrainConfig:
    # 基座：多语 NLI，已经会判蕴含/中立/矛盾；我们只扩一头、再微调。
    model_id: str = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"

    # 学习率：比过拟合检查（2e-4）小一个数量级。全模型微调常用 1e-5~5e-5；
    # 2e-5 折中：学得动，又不太容易冲掉基座已有的矛盾识别能力。
    learning_rate: float = 2e-5

    # AdamW 的权重衰减：轻微正则，减轻小数据死记硬背。过拟合检查时曾关掉。
    weight_decay: float = 0.01

    # 批大小：T4 16GB + max_length=160 用 16 留有余量；4090 也合适。
    # 再大收益有限，且总样本只有四百级，太大等于每轮更新次数太少。
    batch_size: int = 16

    # 序列最长：第 3 步统计拼接后最长约 146 token；当前 pairs.jsonl 实测最长 139。
    # 取 160 留余量，比 256 更省显存/时间，且不会截断现有数据。
    max_length: int = 160

    # 最多训练轮数：数据少，超过这个几乎必定过拟合；真正停点靠早停。
    max_epochs: int = 12

    # 验证损失连续多少轮没有刷新最优就停。2 太敏感，5 又浪费；3 适合小验证集。
    early_stop_patience: int = 3

    # 三个种子：同一套方法换运气，看测试成绩能抖多少。不能用测试集挑种子。
    seeds: tuple[int, ...] = (42, 43, 44)

    # 数据与验证切分种子（题目级），与第 7 步一致，保证可复现。
    pairs_path: str = "data/pairs.jsonl"
    val_split_seed: str = "crossfire-val-2026-11-20"

    # 输出目录：大文件，不进 git（见 .gitignore / out/）。
    output_dir: str = "out/training/run"

    # 日志每隔多少个 batch 打一行（epoch 末尾无论如何都会打）。
    log_every_batches: int = 10

    # 类别权重：balanced（默认）或 sqrt（缓和稀有类过重）。
    class_weight_scheme: str = "balanced"


DEFAULT_CONFIG = TrainConfig()


def config_to_dict(config: TrainConfig) -> dict:
    data = asdict(config)
    data["seeds"] = list(config.seeds)
    return data
