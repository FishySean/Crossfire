"""整条查证流程对外的契约：事件流和结果文件（characterization test）。

最初锁的是 pipeline.run 的外部行为，第 4 步删掉兼容门面后改走组合根的 composition.assemble：
四个端口（抓取、提取、比对、判决）用 tests/fakes.py 的假实现，存储、时钟、心跳线程都是真的。
个别测试锁住的现状本身就像 bug，在对应测试的注释里标了「锁住现状」，
决定修掉时要连同测试一起改，而且是有意识地改。

心跳线程所在模块 adapters.system 的 threading 可以被替换，用来数线程。
socket.connect 被替换成直接报错，用来证明流程没有绕过端口自己联网。
"""

import json
import os
import socket
import threading
from types import SimpleNamespace

import pytest

import crossfire.adapters.system as system
from crossfire.adapters.event_sinks import CallbackEventSink
from crossfire.application.records import run_record
from crossfire.composition import assemble
from crossfire.domain import Mode, Question
from tests.fakes import CallLog, FakeExtractor, FakeFetcher, FakeJudge, FakePairer

QUESTION_ID = "contract-fixture"
QUESTION = "测试问题：某产品当前版本是多少？"
SOURCES = [
    {"url": "https://source-a.example/", "tier": "primary"},
    {"url": "https://source-b.example/", "tier": "primary"},
    {"url": "https://source-c.example/", "tier": "news"},
    {"url": "https://source-d.example/", "tier": "aggregator"},
]
CONFIG = Question.from_dict({"id": QUESTION_ID, "question": QUESTION, "sources": SOURCES})
URLS = [s["url"] for s in SOURCES]

USAGE = {"input_tokens": 10, "output_tokens": 2}

# 前端按这张表解析事件，字段多一个少一个都算破坏契约。
# 这张表是照着当初定死的事件格式手写的，不要改成从代码里反推。
EVENT_FIELDS = {
    "start": {"type", "question", "total_sources"},
    # 第 7 步有意修改：fetch_done 末尾加 unusable_reason；claim_done 加 failed；pair_done 加 scores。
    # 已有键不动，只新增。原因：前端要区分内容不可用 / 提取失败，并显示 NLI 概率。
    "fetch_done": {"type", "url", "ok", "chars", "index", "unusable_reason"},
    "claim_done": {"type", "url", "claim", "tier", "index", "failed"},
    "pair_start": {"type", "total_pairs"},
    "pair_done": {"type", "a_url", "b_url", "relation", "nature", "index", "total", "scores"},
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
    # 第 5a 步有意修改：新增 as_of、provenance 两个键，已有的键不动。原因：造数据集时每条标签要能查到
    # 是哪天的数据、哪个模型、哪版 prompt 产出的。
    "as_of",
    "provenance",
}


def _refuse(*args, **kwargs):
    raise AssertionError("测试里不允许任何真实网络或 API 调用")


@pytest.fixture
def offline_pipeline(monkeypatch, tmp_path):
    """返回一个安装器：按参数装配四个假端口，返回调用记录和 run(on_event=None) -> (结果 dict, 保存位置)。"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("STEEL_API_KEY", raising=False)
    monkeypatch.setattr(socket.socket, "connect", _refuse)

    runs_dir = tmp_path / "runs"

    def install(
        failing_urls=(), unusable_urls=(), failing_pair_urls=None, judge_delay=0.0, mode=Mode.LIVE, heartbeat_seconds=5
    ):
        log = CallLog()
        deps = {
            "fetcher": FakeFetcher(failing_urls=failing_urls, unusable_urls=unusable_urls, mode=mode),
            # 提取是并发的，claim_done 按完成顺序到。倒着完成是最容易暴露「拿完成顺序当来源下标」的情形。
            "extractor": FakeExtractor(log, finish_in_reverse=True),
            "pairer": FakePairer(log, failing_pair_urls=failing_pair_urls),
            "judge": FakeJudge(log, trusted_url=URLS[0], delay=judge_delay),
        }
        def run(on_event=None):
            sink = CallbackEventSink(on_event) if on_event else None
            saved = assemble(**deps, runs_dir=runs_dir, event_sink=sink, heartbeat_seconds=heartbeat_seconds).execute(
                CONFIG
            )
            return run_record(saved.result), saved.location

        return SimpleNamespace(llm_steps=log.steps, runs_dir=runs_dir, run=run)

    return install


def _run_collecting(record):
    events = []
    result, _ = record.run(on_event=events.append)
    return result, events


def test_event_sequence_shape(offline_pipeline):
    record = offline_pipeline()
    _, events = _run_collecting(record)

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
    record = offline_pipeline(failing_urls={URLS[1]})
    result, events = _run_collecting(record)

    fetch = [e for e in events if e["type"] == "fetch_done"]
    claim = [e for e in events if e["type"] == "claim_done"]
    assert sorted(e["index"] for e in fetch) == [0, 1, 2, 3]
    # 第 5b 步有意修改：[e["index"] for e in claim] == [0, 2, 3] → 排序后再比，并且实际到达顺序是倒的。
    # 原因：提取改成并发，claim_done 按完成顺序发出；前端按 index 填卡片，不看到达顺序。
    assert [e["index"] for e in claim] == [3, 2, 0]
    assert sorted(e["index"] for e in claim) == [0, 2, 3]

    url_at = {e["index"]: e["url"] for e in fetch}
    for e in claim:
        assert e["url"] == url_at[e["index"]]

    fetch_errors = [e for e in events if e["type"] == "error" and e["step"] == "fetch"]
    assert len(fetch_errors) == 1
    assert events[[e["type"] for e in events].index("pair_start")]["total_pairs"] == 3

    # 第 3 步有意修改：抓取失败只发 error 事件、failures == [] → 抓取失败以 step="fetch" 进 failures，
    # 原因：backlog「【最高优先级】抓取失败不进 failures」
    assert result["failures"] == [{"step": "fetch", "detail": f"假的抓取失败 {URLS[1]}", "raw": None}]
    assert result["pages_failed"] == 1


def test_pair_failure_is_reported_not_swallowed(offline_pipeline):
    record = offline_pipeline(failing_pair_urls=(URLS[1], URLS[2]))
    events = []
    result, location = record.run(on_event=events.append)

    assert [f["step"] for f in result["failures"]] == ["pair"]
    assert result["failures"][0]["detail"] == "假的 pair 失败"

    pair_errors = [e for e in events if e["type"] == "error" and e["step"] == "pair"]
    assert [e["detail"] for e in pair_errors] == ["假的 pair 失败"]

    failed_pair = next(p for p in result["pairs"] if p.get("failure"))
    assert {failed_pair["a"], failed_pair["b"]} == {URLS[1], URLS[2]}
    assert failed_pair["relation"] is None

    assert events[-1]["type"] == "done"
    # 第 4 步有意修改：result["output_path"] → run() 返回的保存位置。原因：决定 1，位置由 SavedRun.location 给出
    on_disk = json.loads(open(location, encoding="utf-8").read())
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

    result, path = record.run(on_event=on_event)

    on_disk = json.loads(open(path, encoding="utf-8").read())
    assert set(on_disk) == RESULT_FILE_KEYS

    # 第 4 步有意修改：RESULT_FILE_KEYS | {"output_path"} → RESULT_FILE_KEYS，并且与磁盘内容逐字相等。
    # 原因：兼容门面删了，不再往返回值里塞 output_path，位置由 SavedRun.location 给出。
    assert result == on_disk

    assert replaced == [(path[: -len(".json")] + ".json.tmp", path)]
    assert seen_at_done == {"exists": True, "tmp": []}
    assert sorted(p.name for p in record.runs_dir.iterdir()) == [os.path.basename(path)]


def test_accounting(offline_pipeline):
    record = offline_pipeline()
    result, _ = _run_collecting(record)

    assert result["claude_calls"] == 4 + 6 + 1
    assert result["steps"]["extract"]["calls"] == 4
    assert result["steps"]["pair"]["calls"] == 6
    assert result["steps"]["judge"]["calls"] == 1
    assert result["steps"]["fetch"]["calls"] == 4
    assert result["total_input_tokens"] == 11 * USAGE["input_tokens"]
    assert result["total_output_tokens"] == 11 * USAGE["output_tokens"]


def test_without_on_event_no_heartbeat_thread_and_same_result(offline_pipeline, monkeypatch):
    record = offline_pipeline()

    created = []

    def recording_thread(*args, **kwargs):
        created.append(kwargs.get("target").__name__)
        return threading.Thread(*args, **kwargs)

    monkeypatch.setattr(system, "threading", SimpleNamespace(Event=threading.Event, Thread=recording_thread))

    result, _ = record.run()
    assert created == []
    # 第 4 步有意修改：RESULT_FILE_KEYS | {"output_path"} → RESULT_FILE_KEYS。原因同上，兼容门面删了
    assert set(result) == RESULT_FILE_KEYS
    assert result["judgment"]["answer"] == "当前版本是 1.0"

    # 对照组：证明上面的记录器确实能抓到心跳线程，空列表不是因为记录器失灵。
    record.run(on_event=lambda event: None)
    assert created == ["beat"]


def test_heartbeats_only_between_judge_start_and_done(offline_pipeline):
    record = offline_pipeline(judge_delay=0.06, heartbeat_seconds=0.01)
    _, events = _run_collecting(record)

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


def test_unusable_pages_are_not_extracted(offline_pipeline):
    """第 4 步有意修改：原 test_unusable_pages_still_go_to_extract 断言不可用页面照样送进 extract
    （extract 调用 4 次、claim_done 里有它）。原因：backlog「usable 算出来了但没人读」。

    现在不可用页面不提取，fetch_done 报 ok=false 让前端卡片直接进终态，紧跟一条 step=usability 的 error，
    结果文件的 failures 里记一条 usability。抓取本身成功，所以 pages_fetched 不变。
    """
    record = offline_pipeline(unusable_urls={URLS[2]})
    result, events = _run_collecting(record)

    assert record.llm_steps.count("extract") == 3
    assert URLS[2] not in [e["url"] for e in events if e["type"] == "claim_done"]
    fetch_done = next(e for e in events if e["type"] == "fetch_done" and e["url"] == URLS[2])
    assert fetch_done["ok"] is False
    assert events[events.index(fetch_done) + 1] == {"type": "error", "step": "usability", "detail": "too_short"}
    assert result["failures"] == [{"step": "usability", "detail": "too_short", "raw": None}]
    assert result["pages_fetched"] == 4
    page = next(p for p in result["pages"] if p["url"] == URLS[2])
    assert (page["ok"], page["usable"], page["unusable_reason"]) == (True, False, "too_short")


@pytest.mark.parametrize("mode", ["live", "cached"])
def test_mode_is_recorded_in_the_result(offline_pipeline, mode):
    # 第 4 步有意修改：删掉 run(mode=...) 参数，mode 只来自 fetcher。原因：兼容门面删了；
    # 原来的「字符串 mode 被拒绝」挪到 test_composition / test_cli，「mode 与 fetcher 对不上」
    # 在组合根里已经构造不出来：fetcher 就是按 mode 选的。
    result, _ = offline_pipeline(mode=Mode(mode)).run()
    assert result["mode"] == mode
