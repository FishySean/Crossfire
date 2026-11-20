"""组合根：按 Settings 选实现。只构造对象不调用，Anthropic 和 Steel 的客户端构造时都不联网。"""

import queue
from pathlib import Path

import pytest

from crossfire import composition
from crossfire.adapters.anthropic import ClaudeClaimPairer
from crossfire.adapters.steel import CachedPageFetcher, SteelPageFetcher
from crossfire.adapters.storage import CachePageStore, JsonRunRepository
from crossfire.application.events import Start
from crossfire.application.use_cases import PrefetchPages, VerifyQuestion
from crossfire.composition import (
    assemble,
    build_eval_runner,
    build_eval_verifier,
    build_fetcher,
    build_pairer,
    build_prefetcher,
    build_verifier,
    queue_event_sink,
)
from crossfire.config import Settings, SettingsError, eval_snapshot_dir, load_eval_cases
from crossfire.domain import Mode, Question
from tests.fakes import CallLog, FakeExtractor, FakeFetcher, FakeJudge, FakePairer, RecordingSink

QUESTION = Question.from_dict(
    {"id": "comp-q", "question": "?", "sources": [{"url": "https://a.example/", "tier": "primary"}]}
)


def fake_ports():
    log = CallLog()
    return FakeExtractor(log), FakePairer(log), FakeJudge(log, trusted_url=QUESTION.sources[0].url)


def settings(tmp_path, **values):
    base = {
        "ANTHROPIC_API_KEY": "sk-test",
        "STEEL_API_KEY": "steel-test",
        "MODEL_EXTRACT": "model-e",
        "MODEL_PAIR": "model-p",
        "MODEL_JUDGE": "model-j",
        "CROSSFIRE_RUNS_DIR": str(tmp_path / "runs"),
        "CROSSFIRE_CACHE_DIR": str(tmp_path / "cache"),
    }
    return Settings.from_mapping({**base, **values}, env_file=tmp_path / ".env")


@pytest.mark.parametrize(("mode", "kind"), [(Mode.LIVE, SteelPageFetcher), (Mode.CACHED, CachedPageFetcher)])
def test_mode_selects_the_fetcher(tmp_path, mode, kind):
    # 第 4 步从 test_pipeline_contract.py 挪过来：选哪种抓取方式从 _wiring 挪到了组合根。
    fetcher = build_fetcher(settings(tmp_path), QUESTION, mode)
    assert isinstance(fetcher, kind)
    assert fetcher.mode is mode
    if mode is Mode.CACHED:
        assert fetcher.cache_dir == tmp_path / "cache" / "comp-q"


def test_verifier_uses_one_model_per_step_and_the_configured_runs_dir(tmp_path):
    verifier = build_verifier(settings(tmp_path), QUESTION, Mode.CACHED)
    assert isinstance(verifier, VerifyQuestion)
    # 第 5a 步有意修改：读 _extractor._client.model 这类私有属性 → 读结果文件里也会写的 provenance。
    # 原因：每次运行都要记下每步用的模型，测试读这份公开的记录就够了。
    assert {step: item.model for step, item in verifier.provenance.items()} == {
        "extract": "model-e",
        "pair": "model-p",
        "judge": "model-j",
    }
    assert all(item.prompt_version for item in verifier.provenance.values())


# 第 5b 步有意修改：下面几条原来读 verifier._runs、verifier._judge、prefetcher._store 这些私有属性。
# 原因：测试应该看组装出来的东西做了什么（结果存到哪、有没有开心跳计时器），不看它内部叫什么名字。
def test_verifiers_save_runs_where_the_settings_say(tmp_path, monkeypatch):
    dirs = []
    monkeypatch.setattr(composition, "JsonRunRepository", lambda runs_dir: dirs.append(runs_dir) or JsonRunRepository(runs_dir))
    [case] = [c for c in load_eval_cases(Settings.from_mapping({})) if c.id == "python-2026-11"]
    build_verifier(settings(tmp_path), QUESTION, Mode.CACHED)
    build_eval_verifier(settings(tmp_path, CROSSFIRE_EVAL_RUNS_DIR=str(tmp_path / "evals-out")), case)
    assert dirs == [tmp_path / "runs", tmp_path / "evals-out" / "python-2026-11"]


def test_assembled_verifier_saves_into_its_runs_dir(tmp_path):
    saved = assemble(FakeFetcher(mode=Mode.CACHED), *fake_ports(), runs_dir=tmp_path / "runs").execute(QUESTION)
    assert Path(saved.location).parent == tmp_path / "runs"


class SpyTicker:
    started: list[float] = []

    def every(self, seconds, tick):
        SpyTicker.started.append(seconds)
        return lambda: None


def test_heartbeat_timer_runs_only_when_someone_listens(tmp_path, monkeypatch):
    monkeypatch.setattr(composition, "ThreadTicker", SpyTicker)
    SpyTicker.started = []
    assemble(FakeFetcher(), *fake_ports(), runs_dir=tmp_path / "quiet").execute(QUESTION)
    assert SpyTicker.started == []
    sink = RecordingSink()
    assemble(FakeFetcher(), *fake_ports(), runs_dir=tmp_path / "loud", event_sink=sink).execute(QUESTION)
    assert SpyTicker.started == [composition.HEARTBEAT_SECONDS]


def test_provenance_is_the_same_with_or_without_listeners(tmp_path):
    quiet = build_verifier(settings(tmp_path), QUESTION, Mode.CACHED)
    loud = build_verifier(settings(tmp_path), QUESTION, Mode.CACHED, RecordingSink())
    assert loud.provenance == quiet.provenance


def test_mode_must_be_a_mode(tmp_path):
    with pytest.raises(TypeError, match="Mode"):
        build_verifier(settings(tmp_path), QUESTION, "cached")  # type: ignore[arg-type]


def test_cached_runs_do_not_need_steel(tmp_path):
    build_verifier(settings(tmp_path, STEEL_API_KEY=""), QUESTION, Mode.CACHED)


@pytest.mark.parametrize(
    ("mode", "blank", "named"),
    [
        (Mode.CACHED, "ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
        (Mode.LIVE, "STEEL_API_KEY", "STEEL_API_KEY"),
        (Mode.LIVE, "ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    ],
)
def test_missing_key_fails_before_anything_runs(tmp_path, mode, blank, named):
    with pytest.raises(SettingsError, match=named):
        build_verifier(settings(tmp_path, **{blank: ""}), QUESTION, mode)


def test_extractor_gets_the_configured_concurrency(tmp_path, monkeypatch):
    built = []
    real = composition.ClaudeClaimExtractor
    monkeypatch.setattr(composition, "ClaudeClaimExtractor", lambda client, concurrency: built.append(concurrency) or real(client, concurrency))
    build_verifier(settings(tmp_path, CROSSFIRE_EXTRACT_CONCURRENCY="7"), QUESTION, Mode.CACHED)
    assert built == [7]


def test_pairer_setting_picks_the_claude_pairer(tmp_path):
    assert isinstance(build_pairer(settings(tmp_path, PAIRER="claude")), ClaudeClaimPairer)


def test_prefetch_needs_only_steel(tmp_path, monkeypatch):
    stores = []
    monkeypatch.setattr(composition, "CachePageStore", lambda cache_dir: stores.append(cache_dir) or CachePageStore(cache_dir))
    prefetcher = build_prefetcher(settings(tmp_path, ANTHROPIC_API_KEY=""), QUESTION)
    assert isinstance(prefetcher, PrefetchPages)
    assert stores == [tmp_path / "cache" / "comp-q"]
    with pytest.raises(SettingsError, match="STEEL_API_KEY"):
        build_prefetcher(settings(tmp_path, STEEL_API_KEY=""), QUESTION)


def test_eval_never_fetches_live_and_reads_the_case_snapshot(tmp_path):
    [case] = [c for c in load_eval_cases(Settings.from_mapping({})) if c.id == "python-2026-11"]
    configured = settings(tmp_path, CROSSFIRE_EVALS_DIR=str(tmp_path / "evals"))
    verifier = build_eval_verifier(configured, case)
    assert verifier.mode is Mode.CACHED
    assert eval_snapshot_dir(configured, case) == tmp_path / "evals" / "snapshots" / "python-2026-11"


def test_eval_needs_only_anthropic(tmp_path):
    build_eval_runner(settings(tmp_path, STEEL_API_KEY=""))
    with pytest.raises(SettingsError, match="ANTHROPIC_API_KEY"):
        build_eval_runner(settings(tmp_path, ANTHROPIC_API_KEY=""))


def test_queue_sink_puts_event_dicts():
    events = queue.Queue()
    queue_event_sink(events).emit(Start(question="?", total_sources=1))
    assert events.get_nowait() == {"type": "start", "question": "?", "total_sources": 1}
