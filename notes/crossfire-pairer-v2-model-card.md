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

# crossfire-pairer (v2)

Crossfire 查证引擎里的**主张两两比对**小模型：给定同一问题下的两条来源主张，四选一：

| 标签 | 含义 |
|---|---|
| `agree` | 可同时为真，指向同一结论 |
| `contradict` | 不可能同时为真 |
| `same_question_different_scope` | 各自为真，但口径/范围不同 |
| `unrelated` | 谈的不是同一件事（训练保留；**推理默认屏蔽**） |

## 基座与许可证

- 基座：[MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7](https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7)（**MIT**）
- 本仓库权重同样按 **MIT** 发布
- 训练标签由 Claude Sonnet 生成；标签反映的是该模型的判断标准，**不是客观真理**

## 训练数据（相对 v1）

- **474 对**主张（v1 为 335），来自更多真实网页查证题；测试集 **89 对 / 5 题全程冻结**
- 按**题目**切分 train/val/test，避免泄漏
- 训练时对训练集配对做主张 A/B 对调增强（文字完全相同的除外）
- 入选种子：**43**（仅按验证集加权损失；测试分只用于报告）
- 运行目录：`iter2-final-20261127-064414`

## 推理：屏蔽 unrelated

Crossfire 里被比较的主张都回答同一问题，按构造不应出现 `unrelated`。应用侧默认 `NLI_MASK_UNRELATED=1`：把该类 logit 设为 `-inf`（训练与标签体系不变）。开/关对照见仓库 `notes/iter2-mask-eval.json`：6 个种子全部正确→错误 = 0。

## 测试成绩（冻结测试集，89 对；**屏蔽开**）

| 指标 | 数值 |
|---|---|
| 三种子宏平均 F1 | **0.59 ± 0.06** |
| 三种子准确率 | **0.81** |
| 发布模型（seed 43）宏 F1 | **0.55** |
| 发布模型准确率 | **0.81** |

对照：同设置下 v1 三种子宏 F1 0.60 ± 0.06、准确率 0.78。v2 与 v1 F1 打平，因训练数据更多而发布 v2。

## 已知问题

1. 发布种子的测试 macro-F1（0.55）低于同轮 seed 42（0.68）——选型只看验证损失
2. `scope` 召回仍然偏弱
3. 置信度**未校准**（高 `p` ≠ 正确）
4. 标签来自 Claude Sonnet，请自行评估是否符合你的场景与条款

## 输入格式

```python
from crossfire.adapters.nli.encoding import encode_pair

encoded = encode_pair(
    question="Python 目前的最新稳定版本是哪一个？",
    claim_a="最新稳定版是 3.14.7",
    claim_b="当前最新是 3.13",
    published_date_a="2026-10-01",
    published_date_b=None,
)
```

在 Crossfire 里设 `PAIRER=nli`；默认开启 unrelated 屏蔽。

## 复现

- 训练代码：`FishySean/Crossfire` 的 `training/`
- 评估记录：`notes/iteration-2.md`、`notes/iter2-mask-eval.json`
- 权重锁定：环境变量 `NLI_MODEL_REVISION`（上传后的 commit hash）
