---
language:
  - en
  - zh
license: mit
library_name: transformers
tags:
  - text-classification
  - nli
  - crossfire
  - claim-pairing
base_model: MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7
pipeline_tag: text-classification
---

# crossfire-pairer

Crossfire 查证引擎里的**主张两两比对**小模型：给定同一问题下的两条来源主张，四选一：

| 标签 | 含义 |
|---|---|
| `agree` | 可同时为真，指向同一结论 |
| `contradict` | 不可能同时为真 |
| `same_question_different_scope` | 各自为真，但口径/范围不同 |
| `unrelated` | 谈的不是同一件事 |

## 基座与许可证

- 基座：[MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7](https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7)（**MIT**）
- 本仓库权重同样按 **MIT** 发布（基座许可证允许）
- 训练标签由 Claude Sonnet 生成；标签反映的是该模型的判断标准，**不是客观真理**

## 训练数据

- **335 对**主张，来自 **19 道**真实网页查证题（[data/pairs.jsonl](https://github.com/FishySean/Crossfire/blob/main/data/pairs.jsonl)）
- 训练集 / 验证集 / 测试集按**题目**切分（同一题的配对不会跨集合），避免泄漏
- 训练时对训练集**全部**配对做主张 A/B 对调增强（A、B 文字完全相同的除外）；验证与测试不做对调
- 入选种子：**44**（仅按验证集加权损失选型；测试分只用于报告）

## 测试成绩（入选模型，seed 44）

| 指标 | 数值 |
|---|---|
| 准确率 | 0.685 |
| 宏平均 F1 | **0.614** |
| 三种子宏 F1 | 0.500 / 0.612 / 0.614（均值 0.576，波动 0.114） |
| 永远 agree 对照 | 宏 F1 0.246 |
| 基座原生格式对照 | 宏 F1 0.405 |

每类（P / R / F1 / support）：

- agree: 0.833 / 0.769 / 0.800 / 52
- contradict: 0.704 / 0.655 / 0.679 / 29
- same_question_different_scope: 0.667 / 0.250 / 0.364 / 8
- unrelated: — / — / — / 0（测试集无此类）

## 已知问题（请先读）

1. **过度预测 `unrelated`**：测试集 0 条 unrelated，模型却预测了 11 次（多来自 agree/scope）
2. **`scope` 召回只有 0.25**：8 条里只找出 2 条，另有 3 条被判成 unrelated
3. **`contradict` 几乎没比基座更好**：微调 F1 0.679 ≈ 基座原生 0.689
4. **数据量小**（335 对），类别极不均衡
5. 标签来自 Claude Sonnet，公开使用前请自行评估是否符合你的场景与条款

## 输入格式（必须一致）

训练与推理必须调用同一拼接函数，否则效果会 silently 变差：

```python
from crossfire.adapters.nli.encoding import encode_pair

encoded = encode_pair(
    question="Python 目前的最新稳定版本是哪一个？",
    claim_a="最新稳定版是 3.14.7",
    claim_b="当前最新是 3.13",
    published_date_a="2026-10-01",
    published_date_b=None,  # → unknown
)
# tokenizer(encoded.premise, encoded.hypothesis, ...)
```

在 Crossfire 里设 `PAIRER=nli` 即可；程序会走 `NliClaimPairer`，自动用上述编码。

## 不适用的场景

- 需要律师级/医疗级确定性结论的场合
- 测试分布之外的长文档多跳推理
- 把本模型当成「通用 NLI」或 Claude 的平替去服务其他产品（它只针对 Crossfire 的四分类比对）
- 指望它可靠识别 `unrelated` / `scope`（当前明显偏弱）

## 复现与版本

- 训练代码：[FishySean/Crossfire](https://github.com/FishySean/Crossfire) 仓库的 [`training/`](https://github.com/FishySean/Crossfire/tree/main/training)（本 Hugging Face 仓库只放推理权重与说明）
- 训练数据：[data/pairs.jsonl](https://github.com/FishySean/Crossfire/blob/main/data/pairs.jsonl)
- 权重锁定：请使用发布时的 **revision（commit hash）**，对应环境变量 `NLI_MODEL_REVISION`
- 包内 `test_report.json` / `summary.json` 为同一次评测快照
