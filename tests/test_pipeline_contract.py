"""pipeline.run 的特征测试（characterization test）。

这些测试锁住的是 run() 现在「是什么样」，不是它「应该是什么样」。
接下来的重构不应改变外部行为，所以它们就是重构的验收标准。
个别测试锁住的现状本身就像 bug，在对应测试的注释里标了「锁住现状」，
重构时如果决定顺手修掉，要连同测试一起改，而且是有意识地改。

为什么用 monkeypatch：
pipeline.run 没有任何注入点，抓取和 Claude 调用都是模块级 import 进来的，
只能在测试里替换模块属性。这本身就是当前架构缺少依赖注入的证据。
第 2 步（ports + adapters）做完之后，这些测试要改写成直接把假实现传给 use case，
届时删掉 offline_pipeline 这个 fixture 里的全部 setattr。

替换的位置有讲究：pipeline.py 写的是 `from crossfire.steel_client import fetch_pages`，
名字已经绑定在 crossfire.pipeline 里，替换 crossfire.steel_client.fetch_pages 不会生效。
call_structured 同理，被 crossfire.extract 和 crossfire.reconcile 各自绑定了一份。
所以要替换三处：crossfire.pipeline.fetch_pages、crossfire.extract.call_structured、
crossfire.reconcile.call_structured。
"""

import json
import os
import socket
import threading
import time
from types import SimpleNamespace

import pytest

import crossfire.extract
import crossfire.llm
import crossfire.pipeline as pipeline
import crossfire.reconcile
import crossfire.steel_client

QUESTION_ID = "contract-fixture"
QUESTION = "测试问题：某产品当前版本是多少？"
SOURCES = [
    {"url": "https://source-a.example/", "tier": "primary"},
    {"url": "https://source-b.example/", "tier": "primary"},
    {"url": "https://source-c.example/", "tier": "news"},
    {"url": "https://source-d.example/", "tier": "aggregator"},
]
CONFIG = {"id": QUESTION_ID, "question": QUESTION, "sources": SOURCES}
URLS = [s["url"] for s in SOURCES]

USAGE = {"input_tokens": 10, "output_tokens": 2}

# 前端按这张表解析事件，字段多一个少一个都算破坏契约。
# 这张表是照着当初定死的事件格式手写的，不要改成从代码里反推。
EVENT_FIELDS = {
    "start": {"type", "question", "total_sources"},
    "fetch_done": {"type", "url", "ok", "chars", "index"},
    "claim_done": {"type", "url", "claim", "tier", "index"},
    "pair_start": {"type", "total_pairs"},
    "pair_done": {"type", "a_url", "b_url", "relation", "nature", "index", "total"},
    "judge_start": {"type"},
    "heartbeat": {"type", "step", "elapsed"},
    "done": {"type", "judgment", "run_file", "elapsed"},
    "error": {"type", "step", "detail"},
}

# 写到 out/runs/ 的结果文件的顶层键。前端的历史运行查看器和以后造数据集都读这个文件。
RESULT_FILE_KEYS = {
    "question_id",
    "question",
    "mode",
    "started_at",
    "elapsed_seconds",
    "sources",
    "pages_fetched",
    "pages_failed",
    "claude_calls",
    "failures",
    "steps",
    "total_input_tokens",
    "total_output_tokens",
    "pages",
    "claims",
    "pairs",
    "judgment",
}


def _ok_page(url: str, usable: bool = True) -> dict:
    return {
        "url": url,
        "ok": True,
        "title": f"标题 {url}",
        "markdown": f"正文 {url}",
        "links": [],
        "error": None,
        "status_code": 200,
        "usable": usable,
        "unusable_reason": "" if usable else "nav_skeleton",
    }


def _failed_page(url: str) -> dict:
    return {
        "url": url,
        "ok": False,
        "title": None,
        "markdown": None,
        "links": [],
        "error": f"假的抓取失败 {url}",
        "status_code": 503,
        "usable": False,
        "unusable_reason": "fetch_failed",
    }


def _refuse(*args, **kwargs):
    raise AssertionError("测试里不允许任何真实网络或 API 调用")


@pytest.fixture
def offline_pipeline(monkeypatch, tmp_path):
    """装好假抓取和假 Claude，返回一个可调参数的安装器和调用记录。"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("STEEL_API_KEY", raising=False)
    monkeypatch.setattr(crossfire.llm, "Anthropic", _refuse)
    monkeypatch.setattr(crossfire.steel_client, "Steel", _refuse)
    monkeypatch.setattr(crossfire.steel_client, "AsyncSteel", _refuse)
    monkeypatch.setattr(socket.socket, "connect", _refuse)

    runs_dir = tmp_path / "runs"
    monkeypatch.setattr(pipeline, "RUNS_DIR", runs_dir)

    record = SimpleNamespace(llm_steps=[], fetch_kwargs=None, runs_dir=runs_dir)
    lock = threading.Lock()

    def install(failing_urls=(), unusable_urls=(), failing_pair_urls=None, judge_delay=0.0):
        async def fake_fetch_pages(urls, concurrency=8, use_cache=False, cache_dir=None, on_page=None):
            record.fetch_kwargs = {"use_cache": use_cache, "cache_dir": cache_dir}
            pages = []
            for index, url in enumerate(urls):
                if url in failing_urls:
                    page = _failed_page(url)
                else:
                    page = _ok_page(url, usable=url not in unusable_urls)
                if on_page:
                    on_page(index, page)
                pages.append(page)
            return pages

        def fake_call_structured(prompt, schema, step, max_tokens=1000):
            with lock:
                record.llm_steps.append(step)
            usage = dict(USAGE)
            if step == "extract":
                url = next(u for u in URLS if u in prompt)
                return {
                    "claim": f"{url} 说当前版本是 1.0",
                    "evidence": "version 1.0",
                    "source_type": "official_documentation",
                    "confidence": 0.9,
                    "published_date": None,
                    "_usage": usage,
                }
            if step == "pair":
                if failing_pair_urls and all(u in prompt for u in failing_pair_urls):
                    return {"_usage": usage, "_failure": {"step": "pair", "detail": "假的 pair 失败", "raw": "[]"}}
                return {"relation": "agree", "nature": "粒度不同——测试数据", "_usage": usage}
            if step == "judge":
                time.sleep(judge_delay)
                return {
                    "answer": "当前版本是 1.0",
                    "confidence": 0.9,
                    "reasoning": "测试数据",
                    "conflicts": [],
                    "trusted_sources": [URLS[0]],
                    "_usage": usage,
                }
            raise AssertionError(f"未知步骤 {step}")

        monkeypatch.setattr(pipeline, "fetch_pages", fake_fetch_pages)
        monkeypatch.setattr(crossfire.extract, "call_structured", fake_call_structured)
        monkeypatch.setattr(crossfire.reconcile, "call_structured", fake_call_structured)
        return record

    return install


def _run_collecting(config=CONFIG, **kwargs):
    events = []
    result = pipeline.run(config, on_event=events.append, **kwargs)
    return result, events


def test_event_sequence_shape(offline_pipeline):
    offline_pipeline()
    _, events = _run_collecting()

    types = [e["type"] for e in events]
    assert types == (
        ["start"]
        + ["fetch_done"] * 4
        + ["claim_done"] * 4
        + ["pair_start"]
        + ["pair_done"] * 6
        + ["judge_start", "done"]
    )
    for event in events:
        assert set(event) == EVENT_FIELDS[event["type"]], event["type"]

    pair_events = [e for e in events if e["type"] == "pair_done"]
    assert events[types.index("pair_start")]["total_pairs"] == 6
    assert sorted(e["index"] for e in pair_events) == list(range(6))
    assert {e["total"] for e in pair_events} == {6}


def test_claim_index_is_the_source_index_not_the_claim_count(offline_pipeline):
    """这是真实发生过的 bug，必须锁死。

    当初 claim_done.index 发的是「第几条成功的主张」（len(claims) - 1），
    而前端按 index 往一排按来源数预建的卡片槽位里填。只要有一个页面抓取失败，
    后面每条主张都会错位一格，画到别的来源卡片上。假事件永远不会有抓取失败，
    所以只跑假事件时这个 bug 完全不可见，是第一次接真实链路时才暴露的。
    """
    offline_pipeline(failing_urls={URLS[1]})
    result, events = _run_collecting()

    fetch = [e for e in events if e["type"] == "fetch_done"]
    claim = [e for e in events if e["type"] == "claim_done"]
    assert sorted(e["index"] for e in fetch) == [0, 1, 2, 3]
    assert [e["index"] for e in claim] == [0, 2, 3]

    url_at = {e["index"]: e["url"] for e in fetch}
    for e in claim:
        assert e["url"] == url_at[e["index"]]

    fetch_errors = [e for e in events if e["type"] == "error" and e["step"] == "fetch"]
    assert len(fetch_errors) == 1
    assert events[[e["type"] for e in events].index("pair_start")]["total_pairs"] == 3

    # 锁住现状：抓取失败只发 error 事件，不进 failures 数组，
    # 所以命令行摘要末尾那段「⚠️ 本次有 N 次调用解析失败」不会提到它。
    assert result["failures"] == []
    assert result["pages_failed"] == 1


def test_pair_failure_is_reported_not_swallowed(offline_pipeline):
    offline_pipeline(failing_pair_urls=(URLS[1], URLS[2]))
    result, events = _run_collecting()

    assert [f["step"] for f in result["failures"]] == ["pair"]
    assert result["failures"][0]["detail"] == "假的 pair 失败"

    pair_errors = [e for e in events if e["type"] == "error" and e["step"] == "pair"]
    assert [e["detail"] for e in pair_errors] == ["假的 pair 失败"]

    failed_pair = next(p for p in result["pairs"] if p.get("failure"))
    assert {failed_pair["a"], failed_pair["b"]} == {URLS[1], URLS[2]}
    assert failed_pair["relation"] is None

    assert events[-1]["type"] == "done"
    on_disk = json.loads(open(result["output_path"], encoding="utf-8").read())
    assert [f["step"] for f in on_disk["failures"]] == ["pair"]


def test_result_file_structure_and_atomic_write(offline_pipeline, monkeypatch):
    record = offline_pipeline()

    replaced = []
    real_replace = os.replace

    def spy_replace(src, dst):
        replaced.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)

    seen_at_done = {}

    def on_event(event):
        if event["type"] == "done":
            seen_at_done["exists"] = os.path.exists(event["run_file"])
            seen_at_done["tmp"] = sorted(p.name for p in record.runs_dir.glob("*.tmp"))

    result = pipeline.run(CONFIG, on_event=on_event)
    path = result["output_path"]

    on_disk = json.loads(open(path, encoding="utf-8").read())
    assert set(on_disk) == RESULT_FILE_KEYS

    # 锁住现状：output_path 是写完文件之后才塞进返回值的，所以返回值比磁盘上的文件多一个键。
    assert set(result) == RESULT_FILE_KEYS | {"output_path"}

    assert replaced == [(path[: -len(".json")] + ".json.tmp", path)]
    assert seen_at_done == {"exists": True, "tmp": []}
    assert sorted(p.name for p in record.runs_dir.iterdir()) == [os.path.basename(path)]


def test_accounting(offline_pipeline):
    offline_pipeline()
    result, _ = _run_collecting()

    assert result["claude_calls"] == 4 + 6 + 1
    assert result["steps"]["extract"]["calls"] == 4
    assert result["steps"]["pair"]["calls"] == 6
    assert result["steps"]["judge"]["calls"] == 1
    assert result["steps"]["fetch"]["calls"] == 4
    assert result["total_input_tokens"] == 11 * USAGE["input_tokens"]
    assert result["total_output_tokens"] == 11 * USAGE["output_tokens"]


def test_without_on_event_no_heartbeat_thread_and_same_result(offline_pipeline, monkeypatch):
    offline_pipeline()

    created = []

    def recording_thread(*args, **kwargs):
        created.append(kwargs.get("target").__name__)
        return threading.Thread(*args, **kwargs)

    monkeypatch.setattr(pipeline, "threading", SimpleNamespace(Event=threading.Event, Thread=recording_thread))

    result = pipeline.run(CONFIG)
    assert created == []
    assert set(result) == RESULT_FILE_KEYS | {"output_path"}
    assert result["judgment"]["answer"] == "当前版本是 1.0"

    # 对照组：证明上面的记录器确实能抓到心跳线程，空列表不是因为记录器失灵。
    pipeline.run(CONFIG, on_event=lambda event: None)
    assert created == ["beat"]


def test_heartbeats_only_between_judge_start_and_done(offline_pipeline, monkeypatch):
    monkeypatch.setattr(pipeline, "HEARTBEAT_SECONDS", 0.01)
    offline_pipeline(judge_delay=0.06)
    _, events = _run_collecting()

    types = [e["type"] for e in events]
    beats = [i for i, t in enumerate(types) if t == "heartbeat"]
    assert beats, "judge 跑了 6 个心跳周期却一次心跳都没发"
    assert types.index("judge_start") < beats[0]
    assert beats[-1] < types.index("done")

    for i in beats:
        assert set(events[i]) == EVENT_FIELDS["heartbeat"]
        assert events[i]["step"] == "judge"
    elapsed = [events[i]["elapsed"] for i in beats]
    assert elapsed == sorted(elapsed)


def test_unusable_pages_still_go_to_extract(offline_pipeline):
    """锁住现状：steel_client 会给每页算出 usable，但 pipeline 从来不读它。

    导航骨架页、软 404 只要 ok=True 就照样送进 extract 烧 token。
    这是已知的断线，第 4 步接上 usable 之后这条测试要有意识地改写。
    """
    record = offline_pipeline(unusable_urls={URLS[2]})
    result, events = _run_collecting()

    assert record.llm_steps.count("extract") == 4
    assert URLS[2] in [e["url"] for e in events if e["type"] == "claim_done"]
    assert result["pages_fetched"] == 4


@pytest.mark.parametrize(
    ("mode", "use_cache"),
    [("live", False), ("cached", True), ("bogus", False)],
)
def test_mode_selects_cache(offline_pipeline, mode, use_cache):
    """锁住现状：run 不校验 mode，除 "cached" 以外的任何字符串都按 live 跑，
    而且结果文件里会原样记下那个非法值。只有 web 端点在入口处校验了 mode。"""
    record = offline_pipeline()
    result = pipeline.run(CONFIG, mode=mode)

    assert record.fetch_kwargs["use_cache"] is use_cache
    assert record.fetch_kwargs["cache_dir"] == crossfire.steel_client.CACHE_ROOT / QUESTION_ID
    assert result["mode"] == mode
