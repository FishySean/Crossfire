"""命令行入口：组合根换成装好假实现的版本，存储、时钟用真的，结果写进 tmp_path。"""

import json

import pytest

from crossfire import cli, composition
from crossfire.adapters.storage import CachePageStore
from crossfire.application.use_cases import PrefetchPages, RunEvals
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


# ---- eval ----

CASE_YAML = """
id: {id}
question_id: q1
as_of: 2026-09-12
repeats: {repeats}
gold_answer: '{gold}'
evidence:
  - {{url: 'https://a.example/', quote: '1.0'}}
rules:
  - {{kind: leads_with, expected: '{gold}', competitors: [], why: 测试}}
"""


@pytest.fixture
def eval_env(env, monkeypatch):
    run, tmp_path, _ = env
    cases = tmp_path / "evals" / "cases"
    cases.mkdir(parents=True)
    (cases / "right.yaml").write_text(CASE_YAML.format(id="right", repeats=2, gold=r"1\.0"), encoding="utf-8")
    (cases / "wrong.yaml").write_text(CASE_YAML.format(id="wrong", repeats=1, gold=r"2\.0"), encoding="utf-8")

    def fake_runner(settings):
        settings.require(*composition.KEYS_FOR_MODE[Mode.CACHED])

        def verifier_for(case, question):
            log = CallLog()
            return composition.assemble(
                FakeFetcher(mode=Mode.CACHED),
                FakeExtractor(log),
                FakePairer(log),
                FakeJudge(log, trusted_url=question.sources[0].url),
                runs_dir=settings.eval_runs_dir / case.id,
            )

        return RunEvals(verifier_for)

    monkeypatch.setattr(composition, "build_eval_runner", fake_runner)

    def run_eval(*argv, **overrides):
        return run("eval", *argv, CROSSFIRE_EVALS_DIR=str(tmp_path / "evals"),
                   CROSSFIRE_EVAL_RUNS_DIR=str(tmp_path / "eval-runs"), **overrides)

    return run_eval, tmp_path


def test_eval_estimate_only_prints_the_upper_bound_and_runs_nothing(eval_env, capsys):
    run_eval, tmp_path = eval_env
    assert run_eval("--estimate-only") == 0
    out = capsys.readouterr().out
    # q1 有 2 个来源：2 次提取 + 1 次比对 + 1 次判决 = 4；right 跑 2 次，wrong 跑 1 次。
    assert "right" in out and "最多 8 次" in out and "最多 4 次" in out and "合计最多 12 次" in out
    assert not (tmp_path / "eval-runs").exists()


def test_eval_passing_case_exits_zero_and_saves_runs_apart_from_history(eval_env, capsys):
    run_eval, tmp_path = eval_env
    assert run_eval("--case", "right") == 0
    out = capsys.readouterr().out
    assert out.index("预计请求数") < out.index("=== right")
    assert "通过 1/1 道题" in out and "当前版本是 1.0" in out
    assert len(list((tmp_path / "eval-runs" / "right").glob("*.json"))) == 2
    assert not (tmp_path / "runs").exists()


def test_eval_exits_nonzero_when_any_case_fails_and_says_why(eval_env, capsys):
    run_eval, _ = eval_env
    assert run_eval() == 1
    out = capsys.readouterr().out
    assert "通过 1/2 道题" in out
    assert "没通过" in out and "答案里没有标准答案" in out


def test_eval_unknown_case_lists_the_available_ones(eval_env, capsys):
    run_eval, _ = eval_env
    with pytest.raises(SystemExit):
        run_eval("--case", "nope")
    assert "right, wrong" in capsys.readouterr().err


def test_eval_needs_only_the_anthropic_key(eval_env, capsys):
    run_eval, _ = eval_env
    assert run_eval("--case", "right", STEEL_API_KEY="") == 0
    assert run_eval("--case", "right", ANTHROPIC_API_KEY="") == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
