"""组合根：按 Settings 选实现。只构造对象不调用，Anthropic 和 Steel 的客户端构造时都不联网。"""

import queue

import pytest

from crossfire.adapters.anthropic import ClaudeClaimPairer
from crossfire.adapters.steel import CachedPageFetcher, SteelPageFetcher
from crossfire.adapters.storage import CachePageStore, JsonRunRepository
from crossfire.application.events import Start
from crossfire.application.heartbeat import HeartbeatJudge
from crossfire.application.use_cases import PrefetchPages, VerifyQuestion
from crossfire.composition import (
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
from tests.fakes import RecordingSink

QUESTION = Question.from_dict(
    {"id": "comp-q", "question": "?", "sources": [{"url": "https://a.example/", "tier": "primary"}]}
)


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
    assert isinstance(verifier._runs, JsonRunRepository)
    assert verifier._runs.runs_dir == tmp_path / "runs"


def test_heartbeat_wraps_the_judge_only_when_someone_listens(tmp_path):
    quiet = build_verifier(settings(tmp_path), QUESTION, Mode.CACHED)
    loud = build_verifier(settings(tmp_path), QUESTION, Mode.CACHED, RecordingSink())
    assert not isinstance(quiet._judge, HeartbeatJudge)
    assert isinstance(loud._judge, HeartbeatJudge)
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


def test_pairer_setting_picks_the_claude_pairer(tmp_path):
    assert isinstance(build_pairer(settings(tmp_path, PAIRER="claude")), ClaudeClaimPairer)


def test_prefetch_needs_only_steel(tmp_path):
    prefetcher = build_prefetcher(settings(tmp_path, ANTHROPIC_API_KEY=""), QUESTION)
    assert isinstance(prefetcher, PrefetchPages)
    assert isinstance(prefetcher._store, CachePageStore)
    assert prefetcher._store.cache_dir == tmp_path / "cache" / "comp-q"
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
