# Crossfire

查证引擎（hackathon）。当前阶段：验证并封装 [Steel.dev](https://steel.dev) 云端浏览器抓取。

## 本地结果查看器

只读渲染 `out/runs/*.json`，不做任何抓取或模型调用。

```bash
uv sync
python app.py            # 自检 → 选端口 → 就绪后自动开浏览器（uv 环境里用 uv run python app.py）
python app.py --no-browser
```

`app.py` 会在启动前检查工作目录（不在项目根目录会自动切过去）、`.env` 里的
`ANTHROPIC_API_KEY` / `STEEL_API_KEY`、依赖、以及 `out/cache/` 里有没有抓取缓存，
并从 8765 开始挑一个没被占用的端口（最多试到 8775）。

进阶：自己控制参数时直接起 uvicorn。

```bash
uv run uvicorn web.server:app --reload --port 8765
```

没有真实结果时，可生成样例数据：`uv run python scripts/make_sample_runs.py`。

## 页面可用性判断

`crossfire.steel_client.is_usable_page(result) -> (usable, reason)` 识别 “HTTP 200 但内容废掉” 的页面：
反爬软屏蔽（`too_short`）、软 404（`error_page_title`）、数据中心 IP 只拿到导航骨架页（`nav_skeleton`）、
以及抓取本身失败（`fetch_failed`）和空内容（`empty_content`）。阈值是模块级常量，直接改即可。

`fetch_page` / `fetch_pages` / `fetch_live` 的返回 dict 会带上 `usable` 与 `unusable_reason`，
只做标记，是否跳过由调用方决定。

```bash
uv run pytest                                  # 离线跑，使用 tests/fixtures/pages 下的抓取快照
uv run python scripts/capture_page_fixtures.py # 需要联网，重新采集快照
```
