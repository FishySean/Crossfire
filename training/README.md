# 微调 Crossfire 四分类比对模型

**主线：Google Colab（免费 T4）**。打开笔记本一格一格跑即可。  
**备用：RunPod RTX 4090**（要充值；算力自由从加拿大连不上，已弃用）。

---

## 主线：Google Colab

### 一分钟上手

1. 打开笔记本（GitHub 上点 **Open in Colab**，或把下面链接贴进浏览器）：  
   https://colab.research.google.com/github/FishySean/Crossfire/blob/main/training/colab_train.ipynb
2. 菜单 **代码执行程序 → 更改运行时类型 → T4 GPU**
3. 从上往下依次运行每一格（每格上方有中文说明）
4. 结果写在你的 Google Drive：`MyDrive/crossfire-runs/...`
5. 训练不需要任何 API key

### 为什么是 T4 + fp16

T4 算力 **7.5**，**没有硬件 bf16**。不要看 `torch.cuda.is_bf16_supported()` 的默认结果——它在新版 torch 里会把软件模拟也算进去，T4 会误报 True。我们按 `get_device_capability()`：**主版本 ≥ 8 才用 bf16**，否则 fp16 + GradScaler。

- **T4 等（算力 &lt; 8）** → `fp16 autocast` + `GradScaler`
- **4090 等 Ampere+（算力 ≥ 8）** → `bf16 autocast`（不用 GradScaler）

两种都是「计算用低精度、**参数本体仍是 fp32**」。  
这和第 6 步禁止的「用 fp16 权重直接训练」不是一回事。

笔记本进 git 前清掉输出：`uv run python scripts/strip_notebook_outputs.py`（测试会检查 `training/*.ipynb` 没有 outputs）。

### T4 上大概多久

数据很少（增强后约 410 条）：

| 步骤 | 估计 |
|---|---|
| 装依赖 + 下基座 | 3–8 分钟（首次） |
| `--smoke` | 1–3 分钟 |
| 三个种子正式训练 | **约 15–25 分钟** |
| 打包 + fp16 对照 | 1–2 分钟 |

合计大约 **半小时内**（含下载）。Colab 免费，不用盯着计费；但会话闲置会断，所以笔记本会把每个种子同步到 Drive。

### 笔记本做了什么

`training/colab_train.ipynb`：

1. 检查 GPU（`nvidia-smi`）  
2. 挂载 Drive，建 `crossfire-runs`  
3. `git clone` + `uv sync --group train`  
4. 自检 CUDA / bf16  
5. `--smoke` 并打印峰值显存  
6. 三种子正式训练（`--mirror-dir` 指向 Drive）  
7. 展示打包目录大小与 `summary.json`

---

## 命令行（Colab 终端或其它 GPU 机器）

```bash
uv sync --group train
uv run python -m training.train --smoke          # 冒烟
uv run python -m training.train \
  --mirror-dir /content/drive/MyDrive/crossfire-runs/latest
```

没有 GPU 时正式训练会直接退出。本机调试可加 `--allow-cpu`（极慢）。

### 第 10 步：分组 CV 选型（不碰测试集）

```bash
# a 基线
uv run python -m training.train --cv 5 --mirror-dir "$MIRROR/a"
# b 更长训练
uv run python -m training.train --cv 5 --epochs 25 --mirror-dir "$MIRROR/b"
# c 平方根类别权重
uv run python -m training.train --cv 5 --epochs 25 --class-weight-scheme sqrt --mirror-dir "$MIRROR/c"
# d 校准（只报告 ECE）
uv run python -m training.train --cv 5 --epochs 25 --class-weight-scheme sqrt \
  --calibrate-temperature --mirror-dir "$MIRROR/d"
```

`--cv K` 只在 `split=train` 的题目上按题切 K 折；测试集 89 对不会进入任何折。  
选型看 `cv_summary.json` 的 `cv_macro_f1_mean`。胜者再三种子正式训，**那时才**评估测试集。

每个种子结束后会立刻把该种子目录同步到 `--mirror-dir`。全部结束后再打包：

- `package/final_model_fp16/`：fp16 导出的最终模型（约一半体积）
- `package/seeds/seed_*/`：history、曲线、测试报告（**不含**其它种子的大 checkpoint）
- `package/summary.json`、`run_meta.json`、`fp16_vs_fp32.json`

训练全程参数是 fp32；打包才转 fp16，并在测试集上对比有多少条预测不同。

---

## 默认超参（理由见 `training/config.py`）

| 参数 | 默认 | 一句话 |
|---|---|---|
| learning_rate | 2e-5 | 全模型微调常用量级 |
| weight_decay | 0.01 | 轻微正则 |
| batch_size | 16 | T4 / 4090 都合适 |
| max_length | **160** | 第 3 步最长约 146；当前实测 139 |
| max_epochs | 12 | 上限；靠早停（迭代 2 可试 25） |
| early_stop_patience | 3 | 验证损失 3 轮不刷新就停 |
| class_weight_scheme | balanced | 可选 `sqrt`（缓和稀有类权重） |
| seeds | 42,43,44 | 看随机性 |

选型：每个种子按 **验证加权损失** 留最好一轮；三种子之间仍按验证损失选最终模型；**测试集只在全部结束后评估**。

---

## 备用：RunPod RTX 4090

适合 Colab 排队/限卡、或你想要更快时。需要先充值。

1. Deploy：**RTX 4090** + 官方 **PyTorch/CUDA** 模板 + 磁盘约 **40 GB**
2. `git clone` → `uv sync --group train`
3. `uv run python -m training.train --smoke` → 再去掉 `--smoke`
4. 下载 `out/training/run-*/package/`
5. **Terminate**（不要只 Stop——Stop 后磁盘仍计费）

公开价参考（会变）：Community Cloud 约 **$0.34/hr**，Secure 约 **$0.89/hr**  
来源：[RunPod Pricing](https://www.runpod.io/pricing)

三种子粗估 15–30 分钟 → Community 大约 **$0.10–$0.20**。

---

## 本机（无 GPU 钱）

```bash
uv sync --group train
uv run pytest tests/training
uv run python -m training.overfit_check
uv run python -m training.smoke_train
```

不要在本机 CPU 上跑完整三种子。
