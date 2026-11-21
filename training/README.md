# 在 RunPod 上微调 Crossfire 四分类比对模型

这份说明是给你**照着点**的，不是通用云文档。目标：租一张 **RTX 4090**，跑完 **3 个随机种子**，把结果打包下载，然后**彻底删掉机器**。

价格出处（写 README 当天的公开价，之后可能变）：

- [RunPod GPU Cloud Pricing](https://www.runpod.io/pricing)：RTX 4090 **Community Cloud ≈ $0.34/hr**，Secure Cloud ≈ $0.89/hr
- 第三方核对：[ComputePrices – RunPod RTX 4090](https://computeprices.com/providers/runpod/gpus/rtx4090)（2026-11-21 仍写 $0.34 / $0.89）

下面的费用估算用 **Community Cloud $0.34/hr**。若 Community 没货，再选 Secure（更贵）。

---

## 0. 你在本机先确认

仓库是公开的，数据在 git 里（`data/pairs.jsonl`）。本机已经跑通过：

```bash
uv sync --group train
uv run pytest tests/training
uv run python -m training.overfit_check
```

到 RunPod 上不要再跑完整过拟合（浪费钱）；用下面的 `--smoke` 确认 GPU 即可。

---

## 1. 开一台 Pod

1. 打开 [RunPod Console](https://www.runpod.io/console/pods) → **+ Deploy**
2. **GPU**：选 **RTX 4090**（24 GB）。优先 **Community Cloud**（约 $0.34/hr）
3. **模板 / 镜像**：选官方 **PyTorch** 模板（带 CUDA 的那个，例如 “RunPod Pytorch” / PyTorch 2.x + CUDA）。不要选纯 Ubuntu 再自己装 CUDA
4. **Disk（Container disk）**：**40 GB** 够用  
   - 系统 + uv + torch 镜像本身已占一部分  
   - Hugging Face 基座缓存约 0.6–1 GB  
   - 3 个种子 checkpoint + 最终模型约 3–4 GB  
   - 再留余量。太小中途磁盘满会白烧钱
5. **Volume**：可不挂网络盘（这次跑完就 Terminate）；若挂了，Terminate Pod 时确认 volume 是否还要留
6. Deploy → 等状态变成 **Running** → 点 **Connect** → **Jupyter** 或 **SSH/HTTP terminal**

---

## 2. 把代码拿到机器上

在 Pod 终端里：

```bash
cd /workspace
git clone https://github.com/FishySean/Crossfire.git
cd Crossfire
```

仓库公开，**不需要**把 `.env` 或 API key 拷上去（训练不调 Claude）。

确认数据在：

```bash
wc -l data/pairs.jsonl   # 应是 335
```

---

## 3. 装依赖

镜像里通常已有系统 Python。我们用项目自己的锁文件：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env   # 若 uv 不在 PATH

uv sync --group train
```

`train` 组含固定版本的 `torch`、`transformers`、`sentencepiece`、`matplotlib`。  
主程序依赖里**没有** torch——这是故意的。

快速自检：

```bash
uv run python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
# 应看到 True 和 NVIDIA GeForce RTX 4090
```

---

## 4. 先 GPU 冒烟，再正式训练

**冒烟**（约 1–3 分钟）：1 个种子、1 个 epoch、少量 batch，确认 CUDA / 存盘 / 画图都通。

```bash
uv run python -m training.train --smoke
```

看到 `结果目录：...` 且没有 traceback，再开正式训练。

**正式训练**（3 个种子 42/43/44，早停看验证集加权损失）：

```bash
uv run python -m training.train
```

日志里每一轮会打印：

- `train_loss`
- `val_weighted_loss` ← **早停只看这个**
- `val_macro_f1` ← 仅供参考（验证集很小，单类分数噪声大）

每个种子会写 `loss_curve.png`（训练/验证两条线，虚线标出早停那一轮）。

### 预计时间与费用（RTX 4090）

粗算（会因早停提前结束而偏短）：

| 项目 | 估计 |
|---|---|
| 冒烟 | 1–3 分钟 |
| 单种子（最多 12 epoch，常在 4–8 就停） | 约 3–8 分钟 |
| **3 种子合计** | **约 15–30 分钟**（含基座下载与测试评估） |
| Community @$0.34/hr | **约 $0.10–$0.20** |
| 若开着玩 / 调试多半小时 | 按实际小时 × 0.34 |

Secure Cloud @$0.89/hr 则大约乘 2.6。磁盘在 **Stop** 之后仍计费，见最后一节。

---

## 5. 结果在哪、怎么下载

训练结束会打印类似：

```text
结果目录：/workspace/Crossfire/out/training/run-YYYYMMDD-HHMMSS
```

目录里有：

| 路径 | 内容 |
|---|---|
| `final_model/` | **验证损失最低**的那个种子的最优轮次（最终模型） |
| `seeds/seed_*/history.json` | 每轮损失与 val F1 |
| `seeds/seed_*/loss_curve.png` | 损失曲线 |
| `seeds/seed_*/test_report.json` | 该种子在测试集上的完整报告 |
| `summary.json` | 三种子对比、均值与波动、入选种子 |
| `test_report.json` / `test_report.md` | 入选模型的测试报告（宏 F1、每类 P/R/F1、混淆矩阵、两对照组、去相同配对） |
| `run_meta.json` | 超参、`pairs.jsonl` 的 sha256、切分题目 |

**选型规则（重要）：**

1. 每个种子：按 **验证集加权损失** 留最好一轮  
2. 三种子之间：仍按 **验证损失** 选最终模型  
3. **测试集只在全部训练结束后评估**；不看测试集来选种子或停训  

下载：RunPod 网页 → 你的 Pod → **Connect** 旁的文件浏览器 / Jupyter 文件树 → 把整个 `out/training/run-...` 文件夹打包下载到本机。  
也可在终端 `tar czf /workspace/crossfire-run.tgz out/training/run-...` 再下载这个包。

---

## 6. 关机：Stop ≠ Terminate（钱在这里）

| 操作 | 机器 | GPU 计费 | **磁盘计费** |
|---|---|---|---|
| **Stop（停止）** | 关机，磁盘还在 | 停 | **还在收** |
| **Terminate（终止）** | 整台删掉 | 停 | **停** |

很多人第一次租卡会 **Stop 完事**，磁盘按 GB·天继续扣钱。

**正确收尾：**

1. 确认结果已下载到你自己的电脑并解压能打开 `summary.json`
2. 回到 RunPod Console → 该 Pod → **Terminate**（终止）
3. 不要只点 Stop

若你建了 Network Volume，Terminate Pod 后 volume 可能仍计费——不用就删掉 volume。

---

## 默认超参（理由在 `training/config.py` 注释里）

| 参数 | 默认 | 一句话 |
|---|---|---|
| learning_rate | 2e-5 | 全模型微调常用量级 |
| weight_decay | 0.01 | 轻微正则 |
| batch_size | 16 | 4090 上够用，更新次数也够 |
| max_length | 256 | 覆盖我们的拼接输入 |
| max_epochs | 12 | 上限；真正靠早停 |
| early_stop_patience | 3 | 验证损失 3 轮不刷新就停 |
| seeds | 42,43,44 | 看随机性波动 |

改参数优先改 `training/config.py`，或：

```bash
uv run python -m training.train --lr 2e-5 --batch-size 16 --epochs 12 --seeds 42,43,44
```

---

## 本机对照命令（不占 GPU 钱）

```bash
uv sync --group train
uv run pytest tests/training
uv run python -m training.overfit_check
uv run python -m training.smoke_train
```

**不要在本机跑** `python -m training.train` 的完整三种子（CPU 极慢）。完整训练只在 RunPod 上跑。
