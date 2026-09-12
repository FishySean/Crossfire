# Crossfire

查证引擎（hackathon）。当前阶段：验证并封装 [Steel.dev](https://steel.dev) 云端浏览器抓取。

## 本地结果查看器

只读渲染 `out/runs/*.json`，不做任何抓取或模型调用。

```bash
uv sync
uv run uvicorn web.server:app --reload   # 打开 http://127.0.0.1:8000
```

没有真实结果时，可生成样例数据：`uv run python scripts/make_sample_runs.py`。
