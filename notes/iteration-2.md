# 第 10 步：模型迭代记录（iteration 2）

原则：测试集（89 对 / 5 题）全程冻结，只在最终三种子评估时用一次；配置选择只看 **5 折分组 CV 的平均 macro-F1**。

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

## 3. CV 尝试（Colab 上填写）

一次只改一样。指标：CV 平均 macro-F1（± 标准差）。

| 尝试 | 配置 | CV macro-F1 | 备注 |
|---|---|---|---|
| a | 新数据 + epochs=12 + balanced + patience=3 | _待填_ | 基线 |
| b | 同 a，epochs=25 | _待填_ | |
| c | 在 a/b 胜者上改 `sqrt` | _待填_ | |
| d | 胜者 + temperature scaling | _待填_ | 只记 ECE；选型仍看 CV F1 |

ECE（d）：before `_` → after `_`

**CV 胜者：** _

## 4. 最终三种子 × 测试集（只评一次）

| | v1（旧） | v2（本轮） |
|---|---|---|
| test macro-F1 均值 ± 标准差 | 0.576（范围见 README；选中 seed≈0.614） | _待填_ |
| 每类 F1 | _见旧 test_report_ | _待填_ |
| 混淆矩阵 | | _待填_ |
| 与 Claude 一致率 | | _待填_ |
| 单对推理耗时 | | _待填_ |

## 5. 哪些尝试有用

_待 Colab 结果回来后填写：有用 / 没用 / 持平。_

## 6. 花费

_待填实际 Anthropic 用量（bank + batch）。粗估仍 <$6。_
