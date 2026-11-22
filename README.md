# Crossfire

[![test](https://github.com/FishySean/Crossfire/actions/workflows/test.yml/badge.svg)](https://github.com/FishySean/Crossfire/actions/workflows/test.yml)

查证引擎（hackathon）：用 [Steel.dev](https://steel.dev) 云端浏览器抓取多个来源，让 Claude 逐页提取主张、
两两比对找矛盾，最后给出带置信度的结论。

## 配置

```bash
uv sync
cp .env.example .env   # 填 ANTHROPIC_API_KEY 和 STEEL_API_KEY，其余设置都有默认值，见 .env.example 里的注释
```

只有 `crossfire/config.py` 读 `.env` 和环境变量；同名环境变量优先于文件。

### 比对器：Claude 或本地 NLI

| 配置 | 行为 |
|---|---|
| `PAIRER=claude`（默认） | 比对调 Claude，准，每次花钱 |
| `PAIRER=nli` | 比对用自训小模型，**免费、在本机跑**；提取和判决仍用 Claude |

```bash
uv sync --group nli          # 只要推理：torch + transformers + sentencepiece（不含训练用的 matplotlib）
# .env 里：
# PAIRER=nli
# NLI_MODEL=FishySean/crossfire-pairer          # 默认；第一次运行自动下载约 550MB 到 HF 缓存
# NLI_MODEL_REVISION=<上传后的 commit hash>     # 锁版本，必填（HF 模式）
# 开发时可覆盖为本地目录：NLI_MODEL=models/crossfire-pairer-v1
```

`nli` 组与 `train` 组共用同一套 torch/transformers 版本；`train` 额外包含 matplotlib（画损失曲线）和上传用的 huggingface-hub。只跑比对不必装 `train`。

## 命令行

```bash
uv run crossfire verify --question python-latest-version --mode cached   # 页面读缓存，Claude 真跑
uv run crossfire verify --question python-latest-version                 # 默认 --mode live，实时抓取
uv run crossfire verify --all --mode cached
uv run crossfire prefetch --question python-latest-version               # 实时抓一遍存进 out/cache/
uv run crossfire prefetch --all
```

`verify --mode cached` 只要 `ANTHROPIC_API_KEY`；`prefetch` 只要 `STEEL_API_KEY`；`live` 两个都要。
缺 key 时在开始运行之前报错，说明缺哪个、去哪里设置。结果写进 `out/runs/`。

提取和判断的 prompt 里会写明「今天的日期」（结果文件里的 `as_of`）：live 是运行当天，
cached 是缓存页面抓取的那天（页面的 `fetched_at`），不是跑的那天。缓存里有页面没记抓取时间时，
cached 运行在调用模型之前就拒绝，提示用 `prefetch` 重新抓。旧结果文件里的 `as_of: null` 表示当时没告诉模型日期。结果文件的 `provenance` 记着每一步用的模型和 prompt 版本（模板的哈希）。

## 评测

```bash
uv run crossfire eval --estimate-only        # 只打印预计请求数，不调模型
uv run crossfire eval                        # 跑 evals/cases/ 下所有题
uv run crossfire eval --case python-2026-11  # 只跑一道
```

每道题一个 `evals/cases/<id>.yaml`：问题、`as_of`、标准答案、标准答案在快照里的原文依据、判分规则。
页面只读 `evals/snapshots/<id>/` 下的冻结快照（进 git），从不实时抓取；只要 `ANTHROPIC_API_KEY`。
判分是确定性的正则和数字规则，不用模型打分，每条规则都写了 `why`。`repeats` 大于 1 的题每次都对才算通过；
告诉模型的日期和题目的 `as_of` 对不上也算没通过。有题没通过时退出码非 0。结果写进 `out/eval-runs/<id>/`。

## 本地结果查看器

渲染 `out/runs/*.json`，也可以在页面上发起一次查证（SSE 推送进度）。

```bash
python app.py            # 自检 → 选端口 → 就绪后自动开浏览器（uv 环境里用 uv run python app.py）
python app.py --no-browser
```

`app.py` 会在启动前检查工作目录（不在项目根目录会自动切过去）、`.env` 里的 key、依赖、
以及 `out/cache/` 里有没有抓取缓存，并从 8765 开始挑一个没被占用的端口（最多试到 8775）。

进阶：自己控制参数时直接起 uvicorn。

```bash
uv run uvicorn web.server:app --reload --port 8765
```

没有真实结果时，可生成样例数据：`uv run python scripts/make_sample_runs.py`（`--out 目录` 写到别处）。

## 页面可用性判断

`crossfire.domain.usability.is_usable_page(page) -> (usable, reason)` 识别 “HTTP 200 但内容废掉” 的页面：
反爬软屏蔽（`too_short`）、软 404（`error_page_title`）、数据中心 IP 只拿到导航骨架页（`nav_skeleton`）、
以及抓取本身失败（`fetch_failed`）和空内容（`empty_content`）。阈值是模块级常量，直接改即可。
长度门槛都按显示宽度算：汉字、假名、全角标点算 2，其余算 1。

不可用的页面不送去提取主张，在结果的 `failures` 里记一条 `step="usability"`，原因写在 `detail`。
`Page.usable` 每次现算、不存，规则改了以后旧页面的结论跟着变。

## 测试和开发工具

```bash
uv sync                                        # 主程序 + 开发测试依赖（不含 torch）
uv run pytest                                  # 离线跑：零网络、零 API key；不含训练测试
uv run python scripts/capture_page_fixtures.py # 需要联网，重新采集 tests/fixtures/pages 下的快照
uv run python scripts/probe.py --test 1        # Steel 可用性探测，需要 STEEL_API_KEY
uv run python scripts/migrate_runs.py          # 把旧结果文件迁到当前格式，默认只演练；--apply 才写（先整目录备份）
```

**每次提交前**：在干净环境里跑一遍主测试（只 `uv sync`，不要装 `nli` / `train`）。本机若已装过 torch，现有 `.venv` 会掩盖「缺依赖时类型检查 / 启动检查」类问题。

```bash
rm -rf .venv-clean
UV_PROJECT_ENVIRONMENT=.venv-clean uv sync
UV_PROJECT_ENVIRONMENT=.venv-clean uv run pytest   # 必须全部通过、0 skipped
```

### 推理依赖（本地 NLI 比对）与训练依赖

`torch` / `transformers` 很大，不进默认依赖。

```bash
uv sync --group nli                   # 推理：PAIRER=nli 时需要
uv sync --group train                 # 训练：在 nli 之上多 matplotlib 等
uv sync --group e2e                   # 浏览器端到端（Playwright）
uv run playwright install chromium
uv run pytest                         # 主测试：不装推理依赖也必须全部通过、0 skipped
uv run pytest tests/training          # 训练测试（默认 pytest 会忽略这个目录）
uv run pytest tests/e2e               # 前端 e2e（截图写入 docs/screenshots/）
```

CI（`.github/workflows/test.yml`）跑四个任务：`core` / `nli` / `train` / `e2e`。以后以 CI 全绿为准，不以本机结果为准。

正式训练主线是 **Google Colab（免费 T4）**：打开 [`training/colab_train.ipynb`](training/colab_train.ipynb)。说明见 [`training/README.md`](training/README.md)。

发布模型到 Hugging Face（**由你自己登录并执行上传**，默认私有）：

```bash
uv run --group train hf auth login    # Write token：https://huggingface.co/settings/tokens
uv run --group train python scripts/publish_model.py --re-eval
# 把打印的 commit hash 填进 config.DEFAULT_NLI_MODEL_REVISION，再在网页上改成公开
```

训练代码在 `training/`，与 `crossfire/` 主程序分开；只有 `crossfire/adapters/nli/pairer.py` 允许延迟导入 torch。
