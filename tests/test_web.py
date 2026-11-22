"""web/server.py 的特征测试：改 web 之前的安全网。

锁住的是 HTTP 层对前端的契约：SSE 帧格式、响应头、错误码、崩溃时的收尾顺序、历史结果接口。
运行流水线用 tests/fakes.py 的假实现，不碰网络、不要 key。怎么把假实现塞进 server
只在 web_env 这一个 fixture 里，server 内部换了组装方式时只改这里。
"""

import json
import socket

import pytest
import yaml
from fastapi.testclient import TestClient

import web.server as server
from crossfire.composition import assemble
from crossfire.config import Settings
from crossfire.domain import Mode
from tests.fakes import CallLog, FakeExtractor, FakeFetcher, FakeJudge, FakePairer

QUESTIONS = [
    {
        "id": "web-q",
        "question": "当前版本是多少？",
        "sources": [
            {"url": "https://a.example/", "tier": "primary"},
            {"url": "https://b.example/", "tier": "news"},
            {"url": "https://c.example/", "tier": "aggregator"},
        ],
    },
    {"id": "web-empty", "question": "没有来源的问题", "sources": []},
]


class ExplodingExtractor(FakeExtractor):
    def extract(self, question, page, as_of):
        raise RuntimeError("提取器炸了")


def _refuse(*args, **kwargs):
    raise AssertionError("测试里不允许任何真实网络调用")


@pytest.fixture
def web_env(monkeypatch, tmp_path):
    """返回 (client, runs_dir)。crash=True 时提取步骤抛异常。"""
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("STEEL_API_KEY", raising=False)
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    questions_file = tmp_path / "questions.yaml"
    questions_file.write_text(yaml.safe_dump(QUESTIONS, allow_unicode=True), encoding="utf-8")

    def install(crash=False):
        def build(settings, question, mode, event_sink=None, *, pairer=None):
            del pairer  # 测试里用假比对器，忽略入口传来的选择
            log = CallLog()
            return assemble(
                FakeFetcher(mode=mode),
                ExplodingExtractor(log) if crash else FakeExtractor(log),
                FakePairer(log),
                FakeJudge(log, trusted_url="https://a.example/"),
                runs_dir=settings.runs_dir,
                event_sink=event_sink,
            )

        settings = Settings.from_mapping(
            {"CROSSFIRE_RUNS_DIR": str(runs_dir), "CROSSFIRE_QUESTIONS_FILE": str(questions_file)},
            env_file=tmp_path / ".env",
        )
        monkeypatch.setattr(server, "RETRY_DELAY_SECONDS", 0)
        return TestClient(server.create_app(settings, build)), runs_dir

    return install


def sse_events(response):
    """按 SSE 规则切帧，顺便检查每一帧的格式。"""
    body = response.text
    assert body.endswith("\n\n"), "最后一帧也必须以空行结束"
    frames = body[:-2].split("\n\n")
    events = []
    for frame in frames:
        assert frame.startswith("data: "), frame[:40]
        assert "\n" not in frame, "一帧里的 JSON 必须在同一行"
        events.append(json.loads(frame[len("data: ") :]))
    return events


# ---- /api/run/{question_id} ----


def test_run_streams_one_json_event_per_frame_ending_with_done(web_env):
    client, runs_dir = web_env()
    response = client.get("/api/run/web-q?mode=cached")

    assert response.status_code == 200
    events = sse_events(response)
    types = [e["type"] for e in events]
    assert types == (
        ["start"] + ["fetch_done"] * 3 + ["claim_done"] * 3 + ["pair_start"] + ["pair_done"] * 3 + ["judge_start", "done"]
    )
    done = events[-1]
    assert done["judgment"]["answer"] == "当前版本是 1.0"
    assert done["run_file"].startswith(str(runs_dir))
    saved = json.loads(open(done["run_file"], encoding="utf-8").read())
    assert saved["mode"] == "cached"


def test_run_response_headers(web_env):
    client, _ = web_env()
    response = client.get("/api/run/web-q?mode=cached")

    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"


def test_default_mode_is_cached(web_env):
    client, _ = web_env()
    events = sse_events(client.get("/api/run/web-q"))
    saved = json.loads(open(events[-1]["run_file"], encoding="utf-8").read())
    assert saved["mode"] == Mode.CACHED.value


def test_unknown_question_is_404(web_env):
    client, _ = web_env()
    assert client.get("/api/run/no-such-question?mode=cached").status_code == 404


def test_unknown_mode_is_400(web_env):
    client, _ = web_env()
    response = client.get("/api/run/web-q?mode=cahced")
    assert response.status_code == 400
    assert "cahced" in response.json()["detail"]


def test_crash_sends_error_then_done_and_ends_the_stream(web_env):
    """前端把「还没收到 done 流就断了」当成连接中断，所以崩溃时必须先 error 再 done，然后结束。"""
    client, _ = web_env(crash=True)
    events = sse_events(client.get("/api/run/web-q?mode=cached"))

    assert [e["type"] for e in events[-2:]] == ["error", "done"]
    error, done = events[-2:]
    assert error["step"] == "pipeline"
    assert "RuntimeError" in error["detail"] and "提取器炸了" in error["detail"]
    assert set(done) == {"type", "judgment", "run_file", "elapsed"}
    assert done["judgment"] == {} and done["run_file"] == ""
    assert isinstance(done["elapsed"], (int, float))
    assert [e["type"] for e in events].count("done") == 1


def test_missing_key_with_the_real_composition_root_ends_with_error_then_done(tmp_path):
    """不注入假实现：没配 key 时 build_verifier 在联网之前就报错，照样走 error → done 收尾。"""
    questions_file = tmp_path / "questions.yaml"
    questions_file.write_text(yaml.safe_dump(QUESTIONS, allow_unicode=True), encoding="utf-8")
    settings = Settings.from_mapping({"CROSSFIRE_QUESTIONS_FILE": str(questions_file)}, env_file=tmp_path / ".env")
    events = sse_events(TestClient(server.create_app(settings)).get("/api/run/web-q?mode=cached"))

    assert [e["type"] for e in events] == ["error", "done"]
    assert "ANTHROPIC_API_KEY" in events[0]["detail"]


# ---- /api/runs ----


def test_runs_lists_json_files_newest_first(web_env):
    client, runs_dir = web_env()
    import os

    for name, mtime in [("old.json", 1000), ("new.json", 3000), ("mid.json", 2000)]:
        (runs_dir / name).write_text("{}", encoding="utf-8")
        os.utime(runs_dir / name, (mtime, mtime))
    (runs_dir / "ignored.json.tmp").write_text("{", encoding="utf-8")

    runs = client.get("/api/runs").json()
    assert [r["name"] for r in runs] == ["new.json", "mid.json", "old.json"]
    # 第 7 步有意修改：列表项多 pairer 字段（旧文件为「未记录」）。
    assert set(runs[0]) == {"name", "modified_at", "pairer"}
    assert runs[0]["pairer"] == "未记录"
    assert runs[0]["modified_at"] == 3000


def test_runs_is_empty_when_the_directory_is_missing(web_env):
    client, runs_dir = web_env()
    runs_dir.rmdir()
    assert client.get("/api/runs").json() == []


def test_run_file_is_returned_as_json(web_env):
    client, runs_dir = web_env()
    (runs_dir / "q_1.json").write_text('{"question": "?"}', encoding="utf-8")
    assert client.get("/api/runs/q_1.json").json() == {"question": "?"}


@pytest.mark.parametrize(
    "name",
    ["missing.json", "q_1.txt", "..%2Fsecret.json", "%2E%2E%2Fsecret.json", "..%5Csecret.json"],
)
def test_run_file_outside_the_runs_dir_or_not_json_is_404(web_env, name):
    client, runs_dir = web_env()
    (runs_dir / "q_1.txt").write_text("{}", encoding="utf-8")
    (runs_dir.parent / "secret.json").write_text('{"secret": true}', encoding="utf-8")

    response = client.get(f"/api/runs/{name}")
    assert response.status_code == 404
    assert "secret" not in response.text


def test_symlink_pointing_outside_the_runs_dir_is_404(web_env):
    """上面那几个 ../ 多半在路由匹配时就被挡住了；这条才真正走到 server 自己的越界检查。"""
    client, runs_dir = web_env()
    secret = runs_dir.parent / "secret.json"
    secret.write_text('{"secret": true}', encoding="utf-8")
    (runs_dir / "link.json").symlink_to(secret)

    response = client.get("/api/runs/link.json")
    assert response.status_code == 404
    assert "secret" not in response.text


def test_half_written_run_file_is_422(web_env):
    client, runs_dir = web_env()
    (runs_dir / "broken.json").write_text('{"question": ', encoding="utf-8")
    response = client.get("/api/runs/broken.json")
    assert response.status_code == 422
    assert "invalid or partially written JSON" in response.json()["detail"]


# ---- /api/questions ----


def test_questions_lists_id_text_and_source_count(web_env):
    client, _ = web_env()
    assert client.get("/api/questions").json() == [
        {"id": "web-q", "question": "当前版本是多少？", "total_sources": 3},
        {"id": "web-empty", "question": "没有来源的问题", "total_sources": 0},
    ]


# ---- /api/fake-run ----


def test_fake_run_streams_a_scripted_run(web_env):
    client, _ = web_env()
    events = sse_events(client.get("/api/fake-run/normal?speed=1000"))
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "done"


def test_unknown_fake_scenario_is_404(web_env):
    client, _ = web_env()
    assert client.get("/api/fake-run/nope").status_code == 404


def test_index_and_static_files_are_served(web_env):
    client, _ = web_env()
    assert client.get("/").status_code == 200


# ---- /api/ask ----


def test_ask_estimate_and_run_with_injected_asker(tmp_path, monkeypatch):
    """estimate 返回费用；run 推送找来源事件并以 done 收尾（来源不足提前停）。"""
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    from crossfire.application.use_cases.ask_question import AskQuestion, AskStopped, estimate_ask_cost
    from crossfire.domain.pricing import ModelPrice

    price = ModelPrice(input_per_mtok=3.0, output_per_mtok=15.0)
    settings = Settings.from_mapping(
        {"CROSSFIRE_RUNS_DIR": str(tmp_path / "runs"), "MAX_COST_PER_QUESTION": "1.0"},
        env_file=tmp_path / ".env",
    )

    class StubAsk:
        def __init__(self, *args, **kwargs):
            self._sink = kwargs.get("event_sink")

        def estimate(self, text: str):
            return estimate_ask_cost(
                pairer_free=True,
                max_cost_usd=1.0,
                search_per_thousand_usd=10.0,
                steel_per_scrape_usd=0.005,
                sonnet_price=price,
            )

        def execute(self, text: str):
            from crossfire.application.events import SourceSearchStart, SourcesInsufficient

            if self._sink:
                self._sink.emit(SourceSearchStart(question=text, question_id="u-test"))
                self._sink.emit(
                    SourcesInsufficient(
                        kept=0,
                        found=1,
                        filtered=1,
                        detail="可用来源 0 个，少于 4",
                    )
                )
            est = self.estimate(text)
            return AskStopped(reason="too_few_sources", detail="可用来源 0 个，少于 4", estimate=est, found=1, kept=0)

    client = TestClient(server.create_app(settings, build_ask=lambda *a, **k: StubAsk(*a, **k)))
    estimate = client.post("/api/ask/estimate", json={"question": "Python 最新版？", "pairer": "nli"}).json()
    assert estimate["pairer"] == "nli"
    assert "total_usd" in estimate["estimate"]
    assert estimate["estimate"]["over_budget"] is False

    events = sse_events(client.post("/api/ask/run", json={"question": "Python 最新版？", "pairer": "nli"}))
    types = [e["type"] for e in events]
    assert "source_search_start" in types
    assert "sources_insufficient" in types
    assert "ask_stopped" in types
    assert types[-1] == "done"
    assert events[-1].get("ask_stopped") is True


def test_ask_estimate_rejects_empty_question(web_env):
    client, _ = web_env()
    # 注入会走到真实 build_ask；空问题应在校验处 400，不必真组装。
    # 用 create_app 默认 ask builder 会要 key；这里只测 body 校验——改测 pydantic min_length。
    response = client.post("/api/ask/estimate", json={"question": "", "pairer": "claude"})
    assert response.status_code == 422


def test_fake_ask_scenarios(web_env):
    client, _ = web_env()
    for name in ("ask-normal", "ask-insufficient", "ask-cost-limit"):
        events = sse_events(client.get(f"/api/fake-run/{name}?speed=1000"))
        assert events[-1]["type"] == "done"
    types = [e["type"] for e in sse_events(client.get("/api/fake-run/ask-insufficient?speed=1000"))]
    assert "sources_insufficient" in types
    types = [e["type"] for e in sse_events(client.get("/api/fake-run/ask-cost-limit?speed=1000"))]
    assert "ask_cost_rejected" in types
    assert client.get("/static/app.js").status_code == 200
