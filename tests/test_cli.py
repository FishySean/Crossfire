"""命令行入口：组合根换成装好假实现的版本，存储、时钟用真的，结果写进 tmp_path。"""

import json

import pytest

from crossfire import cli, composition
from crossfire.adapters.storage import CachePageStore
from crossfire.application.use_cases import PrefetchPages
from crossfire.config import Settings
from crossfire.domain import Mode
from tests.fakes import CallLog, FakeExtractor, FakeFetcher, FakeJudge, FakePairer

QUESTIONS_YAML = """
- id: q1
  question: 第一个问题？
  sources:
    - {url: 'https://a.example/', tier: primary}
    - {url: 'https://b.example/', tier: news}
- id: q2
  question: 第二个问题？
  sources:
    - {url: 'https://c.example/', tier: primary}
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    questions = tmp_path / "questions.yaml"
    questions.write_text(QUESTIONS_YAML, encoding="utf-8")
    values = {
        "ANTHROPIC_API_KEY": "sk-test",
        "STEEL_API_KEY": "steel-test",
        "CROSSFIRE_RUNS_DIR": str(tmp_path / "runs"),
        "CROSSFIRE_CACHE_DIR": str(tmp_path / "cache"),
        "CROSSFIRE_QUESTIONS_FILE": str(questions),
    }
    built = []

    def fake_verifier(settings, question, mode, event_sink=None):
        settings.require(*composition.KEYS_FOR_MODE[mode])
        built.append((question.id, mode))
        log = CallLog()
        return composition.assemble(
            FakeFetcher(mode=mode),
            FakeExtractor(log),
            FakePairer(log),
            FakeJudge(log, trusted_url=question.sources[0].url),
            runs_dir=settings.runs_dir,
            event_sink=event_sink,
        )

    def fake_prefetcher(settings, question):
        settings.require(*composition.KEYS_FOR_PREFETCH)
        return PrefetchPages(FakeFetcher(failing_urls={"https://b.example/"}), CachePageStore(settings.cache_dir / question.id))

    monkeypatch.setattr(composition, "build_verifier", fake_verifier)
    monkeypatch.setattr(composition, "build_prefetcher", fake_prefetcher)

    def run(*argv, **overrides):
        settings = Settings.from_mapping({**values, **overrides}, env_file=tmp_path / ".env")
        return cli.main(list(argv), settings=settings)

    return run, tmp_path, built


def test_verify_one_question_prints_the_report_and_saves_the_run(env, capsys):
    run, tmp_path, built = env
    assert run("verify", "--question", "q1", "--mode", "cached") == 0

    out = capsys.readouterr().out
    assert "问题：第一个问题？" in out
    assert "回答：当前版本是 1.0" in out
    [saved] = list((tmp_path / "runs").glob("q1_*.json"))
    assert f"完整结果：{saved}" in out
    assert json.loads(saved.read_text(encoding="utf-8"))["mode"] == "cached"
    assert built == [("q1", Mode.CACHED)]


def test_mode_defaults_to_live(env):
    run, _, built = env
    run("verify", "--question", "q1")
    assert built == [("q1", Mode.LIVE)]


def test_verify_all_runs_every_question(env, capsys):
    run, tmp_path, built = env
    assert run("verify", "--all", "--mode", "cached") == 0
    assert [q for q, _ in built] == ["q1", "q2"]
    assert "全部 2 个问题总耗时" in capsys.readouterr().out


def test_bad_mode_is_rejected_by_the_parser(env, capsys):
    run, _, built = env
    with pytest.raises(SystemExit) as caught:
        run("verify", "--question", "q1", "--mode", "cahced")
    assert caught.value.code == 2
    assert "cahced" in capsys.readouterr().err
    assert built == []


def test_unknown_question_lists_the_available_ones(env, capsys):
    run, _, _ = env
    with pytest.raises(SystemExit):
        run("verify", "--question", "nope")
    assert "q1, q2" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["verify"], ["verify", "--all", "--question", "q1"], ["prefetch"], []])
def test_targets_are_required_and_exclusive(env, argv):
    run, _, _ = env
    with pytest.raises(SystemExit):
        run(*argv)


def test_missing_key_prints_where_to_set_it_without_a_traceback(env, capsys):
    run, tmp_path, _ = env
    assert run("verify", "--question", "q1", "--mode", "live", STEEL_API_KEY="") == 2
    err = capsys.readouterr().err
    assert "STEEL_API_KEY" in err and "Traceback" not in err
    assert not (tmp_path / "runs").exists()


def test_cached_verify_runs_without_steel(env):
    run, _, _ = env
    assert run("verify", "--question", "q1", "--mode", "cached", STEEL_API_KEY="") == 0


def test_prefetch_writes_every_page_into_the_cache(env, capsys):
    run, tmp_path, _ = env
    assert run("prefetch", "--question", "q1", ANTHROPIC_API_KEY="") == 0

    out = capsys.readouterr().out
    assert "=== q1 ===" in out
    assert "ok" in out and "失败 假的抓取失败 https://b.example/" in out
    assert len(list((tmp_path / "cache" / "q1").glob("*.json"))) == 2


def test_prefetch_all(env, capsys):
    run, tmp_path, _ = env
    assert run("prefetch", "--all") == 0
    assert sorted(p.name for p in (tmp_path / "cache").iterdir()) == ["q1", "q2"]
