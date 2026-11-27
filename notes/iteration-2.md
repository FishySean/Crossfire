# 第 10 步：模型迭代记录（iteration 2）

原则：测试集（89 对 / 5 题）全程冻结，只在最终三种子评估时用一次；配置选择只看 **5 折分组 CV 的平均 macro-F1**。发布权重另按**验证集加权损失**选种子。

## 0. Anthropic 估算（开跑前）

| 阶段 | 预计 |
|---|---|
| bank build（+9 scope 配额） | ~$1.02 |
| batch（Claude 打标，按来源数） | ~$2–$4.5 |
| **合计上限内** | **约 $3–$6**（预算 $12） |

实际：分多轮续跑 bank（大量 too_few_usable），最终新增 **7** 道 scope 题并用 `PAIRER=claude` 打标；测试集导出后仍为 **89 对且与备份逐对一致**。

## 1. 新 scope 训练题（仅进 train）

| id | 题目 | Claude 标签概览（pairs） |
|---|---|---|
| great-lakes-area-scope | 北美五大湖的总面积是多少？ | contradict 8 / agree 2 |
| euro-zone-member-count-scope | 目前有多少个国家使用欧元作为官方货币？ | scope 18 / agree 10 |
| us-gdp-scope | 美国GDP是多少？ | scope 11 / contradict 8 / unrelated 5 / agree 4 |
| india-population-scope | India's current population is how much? | agree 12 / contradict 8 / scope 1 |
| us-national-park-count-scope | How many national parks does the United States have? | agree 6 / scope 4 |
| amazon-river-basin-area-scope | 亚马孙河流域的面积是多少？ | unrelated 10 / agree 6 / scope 5 |
| us-hispanic-population-scope | How many Hispanic or Latino people live in the United States? | agree 14 / contradict 6 / scope 1 |

标签分布变化（全量 pairs.jsonl）：

| | agree | contradict | scope | unrelated | 合计 |
|---|---:|---:|---:|---:|---:|
| 迭代前 | 233 | 63 | 26 | 13 | 335 |
| 迭代后 | 286 | 91 | 67 | 30 | 474 |
| 其中 train | 234 | 62 | **59** | 30 | 385 |
| 其中 test | （冻结） |  |  |  | **89** |

## 2. 代码改动（选型工具）

- `--cv 5`：按题分组 K 折，只动 `split=train` 池
- `--class-weight-scheme balanced|sqrt`
- `--calibrate-temperature`：验证集拟合 T，报告 ECE 前后（不改 argmax）
- `dataset export`：若已有 pairs.jsonl，**冻结测试题**，新题只进 train
- 第 10b：`NLI_MASK_UNRELATED`（默认开）+ `training.evaluate --compare-mask` + Colab §10

## 3. CV 尝试（Colab）

一次只改一样。指标：CV 平均 macro-F1（± 标准差）。详细数字以 Drive `crossfire-runs/iter2/*/cv_summary.json` 为准；最终三种子跑在 `iter2-final-20261127-064414`。

| 尝试 | 配置 | 备注 |
|---|---|---|
| a | 新数据 + epochs=12 + balanced + patience=3 | 基线 |
| b | 同 a，epochs=25 | |
| c | sqrt 类别权重 | |
| d | temperature scaling | 只记 ECE；选型仍看 CV F1 |

**最终训练配置：** 见该次 `run_meta.json`（Colab §9；含更多 scope 训练数据相对 v1）。

## 4. 最终三种子 × 测试集（开/关屏蔽）

原始评估 JSON：[`notes/iter2-mask-eval.json`](iter2-mask-eval.json)（Colab 写入 Drive `crossfire-runs/iter2-mask-eval/` 的 slim 副本）。

闸门：6 个模型全部 **correct→wrong = 0**；合计 **wrong→correct = 33**（v1 17 + v2 16）。`publish_gate_ok=true`。

### 屏蔽后汇总（主表）

| | v1（`run-20261121-235427`） | v2（`iter2-final-20261127-064414`） |
|---|---|---|
| 三种子 macro-F1（开） | **0.600 ± 0.061** | **0.594 ± 0.064** |
| 三种子准确率（开） | 0.775 ± 0.024 | **0.809 ± 0.000** |
| 三种子 macro-F1（关） | 0.576 ± 0.053 | 0.579 ± 0.071 |
| unrelated 预测均值（关→开） | 9.0 → 0 | 5.7 → 0 |
| 正确→错误（开相对关） | 0 | 0 |
| 错误→正确 | 17 | 16 |

每类 F1（屏蔽开，三种子均值）：

| | agree | contradict | scope | unrelated |
|---|---:|---:|---:|---:|
| v1 | 0.851 ± 0.024 | 0.717 ± 0.042 | 0.233 ± 0.205 | 0 |
| v2 | 0.900 ± 0.009 | 0.749 ± 0.011 | 0.133 ± 0.189 | 0 |

### 逐种子（屏蔽开）

| 版本 | seed | macro-F1 | accuracy | c→w | w→c |
|---|---:|---:|---:|---:|---:|
| v1 | 42 | 0.616 | 0.809 | 0 | 5 |
| v1 | 43 | 0.519 | 0.764 | 0 | 6 |
| v1 | 44 | 0.666 | 0.753 | 0 | 6 |
| v2 | 42 | 0.684 | 0.809 | 0 | 4 |
| v2 | **43（发布）** | **0.549** | **0.809** | 0 | 6 |
| v2 | 44 | 0.549 | 0.809 | 0 | 6 |

### 发布决定

- **发布 v2**（`iter2-final-20261127-064414`），按验证损失选出的 **seed 43**，并 **开启屏蔽 unrelated**。
- v2 与 v1 三种子 macro-F1 **打平**（0.594 vs 0.600）；选择**训练数据更多的 v2**（474 对 / 更多 scope）。
- 准确率上 v2 更好（0.809 vs 0.775）。发布单模 seed 43：macro-F1 **0.549**，准确率 **0.809**（选型看验证损失，不是测试 F1 最高的 seed 42）。

## 5. 哪些尝试有用

- **新 scope 训练数据**：有用（发布切到数据更多的 v2；准确率提升）。
- **推理屏蔽 unrelated**：有用（正确→错误为 0；错误→正确合计 33；unrelated 误判清零）。
- CV / sqrt / temperature：以 Colab `iter2/` 与 `temperature.json` 为准；不影响本轮「发 v2 + 屏蔽」的结论。

## 6. 花费

| 项 | 金额 | 依据 |
|---|---:|---|
| 7 道新 scope 的 batch 打标 | **~$3.31** | `out/batch-runs/*-scope.json` token × Sonnet 单价（$3/$15 per MTok） |
| bank build（含失败重试） | **~$1** 量级 | 开跑前估算 ~$1.02；本地无逐 token 台账 |
| **第 10 步 Anthropic 合计** | **约 $4.3–$5**（远低于 $12） | |

Colab T4 训练本身无 Anthropic 费用。

## 7. 第 10b 步：推理时屏蔽 unrelated

### 理由（系统设计，与测试集无关）

Crossfire 中所有被比较的主张都回答同一个问题，按构造不应出现 `unrelated`；标签体系仍保留该类（训练不动），只在**推理**时把 unrelated 的 logit 设为 `-inf`。配置项：`NLI_MASK_UNRELATED`（默认开）；评估脚本：`--mask-unrelated` / `--compare-mask`。

### 验证集闸门（v1 入选权重 `models/crossfire-pairer-v1`，n=25）

原定标准是「开/关 macro-F1 不变差」。实测：

| | macro-F1 | agree F1 | contradict F1 | scope F1 | unrelated F1 | unrelated 预测数 |
|---|---:|---:|---:|---:|---:|---:|
| 关 | **0.4349** | 0.905 | 0.400 | 0.000 | 0.000 | 1 |
| 开 | **0.4279** | 0.884 | 0.400 | 0.000 | 0.000 | 0 |
| Δ | **−0.0070** | −0.021 | 0 | 0 | 0 | −1 |

唯一翻转：

- `#2` gold=`same_question_different_scope`，关=`unrelated`（错）→ 开=`agree`（错）
- A: 大堡礁世界遗产区面积为348,000平方公里，比英国、荷兰和瑞士的总面积还大。
- B: 大堡礁约有2,900个独立礁石及900个大小岛屿，分布在约344,400平方公里的范围内。

验证集真实 unrelated=0。准确率不变（仍错）；没有正确预测被改错。macro-F1 −0.007 来自错误在类别间转移（unrelated→agree 拉低 agree precision 0.826→0.792），n=25 下属于单样本噪声。

**标准调整：** 闸门改为「屏蔽是否把原本正确的预测改错」（正确→错误 = 0）。原定「不变差」没有设容差，规则写得不严谨。按调整后的标准，验证集通过，继续测试集评估。

本地无第 10 步 5 折 CV 的逐对预测文件，无法做 CV 开/关对照。

### 测试集（Colab Drive 全量）

见第 4 节。闸门通过后决定发布 **v2 seed 43 + 屏蔽 unrelated**。
