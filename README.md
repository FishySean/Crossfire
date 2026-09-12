# Crossfire

查证引擎（hackathon）。当前阶段：验证并封装 [Steel.dev](https://steel.dev) 云端浏览器抓取。

## 本地结果查看器

只读渲染 `out/runs/*.json`，不做任何抓取或模型调用。

```bash
uv sync
uv run uvicorn web.server:app --reload   # 打开 http://127.0.0.1:8000
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
