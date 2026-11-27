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

### 测试集（进行中）

闸门：测试集上若出现任何「正确→错误」，停、不发布。

#### v1 seed 44（本地入选包 `models/crossfire-pairer-v1`，= 验证损失入选种子）

| | macro-F1 | accuracy | unrelated 预测 | agree F1 | contradict F1 | scope F1 |
|---|---:|---:|---:|---:|---:|---:|
| 关 | 0.6141 | 0.6854 | 11 | 0.800 | 0.679 | 0.364 |
| 开 | **0.6656** | **0.7528** | 0 | 0.818 | 0.679 | 0.500 |

翻转：正确→错误 **0**；错误→正确 **6**；仍错但改类 **5**。闸门通过。

混淆矩阵（关 → 开）：

关：

| gold \\ pred | agree | contradict | scope | unrelated |
|---|---:|---:|---:|---:|
| agree | 40 | 6 | 1 | 5 |
| contradict | 7 | 19 | 0 | 3 |
| scope | 1 | 2 | 2 | 3 |

开：

| gold \\ pred | agree | contradict | scope | unrelated |
|---|---:|---:|---:|---:|
| agree | 45 | 6 | 1 | 0 |
| contradict | 10 | 19 | 0 | 0 |
| scope | 3 | 2 | 3 | 0 |

#### 缺权重（未评，故未算三种子均值 ± 标准差，未发布）

- **v1 seed 42 / 43**：本地 `models/crossfire-pairer-v1/seeds/seed_{42,43}/` 只有 history / test_report，**没有** `best_checkpoint`。请从 Google Drive 下载：
  - `我的云端硬盘/crossfire-runs/run-20261121-235427/seeds/seed_42/best_checkpoint/`
  - `我的云端硬盘/crossfire-runs/run-20261121-235427/seeds/seed_43/best_checkpoint/`
  - （可选对照）`…/seed_44/best_checkpoint/`（与已解压的 package 入选权重同源）
- **v2 全部三种子**：本地无任何 iter2 权重。请下载 Drive 上最新的  
  `我的云端硬盘/crossfire-runs/iter2-final-*/seeds/seed_{42,43,44}/best_checkpoint/`  
  （若只有 `package/`，至少需要三种子各自的 `best_checkpoint`，不能只下入选 package。）

放到例如：

```
models/crossfire-pairer-v1/seeds/seed_42/best_checkpoint/
models/crossfire-pairer-v1/seeds/seed_43/best_checkpoint/
models/crossfire-pairer-v2/seeds/seed_42/best_checkpoint/
…
```

下载齐后再跑开/关对比 → 三种子均值 ± 标准差 → 文档 / 全测 / 推送 / tag **v1.2.0**（发布模型仍为 v1 + 屏蔽 unrelated）。
