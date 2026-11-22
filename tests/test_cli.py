"""命令行入口：组合根换成装好假实现的版本，存储、时钟用真的，结果写进 tmp_path。"""

import json

import pytest

from crossfire import cli, composition
from crossfire.adapters.storage import CachePageStore
from crossfire.application.use_cases import PrefetchPages, RunEvals, RunJudgeEvals
from crossfire.config import Settings
from crossfire.domain import Mode
from tests.fakes import CallLog, FakeClock, FakeExtractor, FakeFetcher, FakeJudge, FakePairer

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
        "CROSSFIRE_USER_QUESTIONS_DIR": str(tmp_path / "user-questions"),
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


def test_ask_prints_estimate_and_respects_yes(env, monkeypatch, capsys):
    from crossfire.application.use_cases.ask_question import AskEstimate, AskStopped
    from crossfire.domain.pricing import ModelPrice

    price = ModelPrice(input_per_mtok=3.0, output_per_mtok=15.0)
    estimate = AskEstimate(
        searches=6,
        steel_pages=8,
        extract_calls=4,
        pair_calls=0,
        judge_calls=1,
        search_usd=0.06,
        steel_usd=0.04,
        anthropic_usd=0.1,
        pair_usd=0.0,
        pairer_free=True,
        max_cost_usd=1.0,
        low_usd=0.2,
        high_usd=0.4,
        low_sources=4,
        high_sources=8,
    )

    class StubAsk:
        def __init__(self, *a, **k):
            pass

        def estimate(self, text):
            return estimate

        def execute(self, text):
            return AskStopped(reason="too_few_sources", detail="可用来源 0 个，少于 4", estimate=estimate)

    monkeypatch.setattr(composition, "build_ask_question", lambda *a, **k: StubAsk())
    run, _, _ = env
    assert run("ask", "Python 最新版？", "--yes", "--pairer", "nli") == 1
    out = capsys.readouterr()
    assert "预计费用" in out.out
    assert "提前停止" in out.err


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
    assert run("verify", "--question", "q1", "--mode", "live", FETCHER="steel", STEEL_API_KEY="") == 2
    err = capsys.readouterr().err
    assert "STEEL_API_KEY" in err and "Traceback" not in err
    assert not (tmp_path / "runs").exists()


def test_cached_verify_runs_without_steel(env):
    run, _, _ = env
    assert run("verify", "--question", "q1", "--mode", "cached", STEEL_API_KEY="") == 0


def test_cached_verify_refuses_a_snapshot_without_fetch_time_and_says_why(env, monkeypatch, capsys):
    run, tmp_path, _ = env
    log = CallLog()

    def undated_verifier(settings, question, mode, event_sink=None):
        return composition.assemble(
            FakeFetcher(mode=mode, fetched_at=None),
            FakeExtractor(log),
            FakePairer(log),
            FakeJudge(log, trusted_url=question.sources[0].url),
            runs_dir=settings.runs_dir,
            event_sink=event_sink,
        )

    monkeypatch.setattr(composition, "build_verifier", undated_verifier)
    assert run("verify", "--question", "q1", "--mode", "cached") == 2
    err = capsys.readouterr().err
    assert "没有记录抓取时间" in err and "crossfire prefetch" in err and "Traceback" not in err
    assert log.steps == []
    assert not (tmp_path / "runs").exists()


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


JUDGE_CASE_YAML = """
id: judge-q1
kind: judge
question_id: q1
snapshot: right
as_of: 2026-09-12
gold_answer: '1.0'
evidence:
  - {url: 'https://a.example/', quote: '1.0'}
rules:
  - {kind: leads_with, expected: '1\\.0', competitors: [], why: 测试}
"""


def test_eval_runs_judge_cases_on_their_frozen_inputs_one_request_each(eval_env, monkeypatch, capsys):
    run_eval, tmp_path = eval_env
    (tmp_path / "evals" / "cases" / "judge-q1.yaml").write_text(JUDGE_CASE_YAML, encoding="utf-8")
    claim = {"url": "https://a.example/", "tier": "primary", "claim": "1.0", "evidence": "1.0", "source_type": None,
             "confidence": 0.9, "published_date": None, "usage": {"input_tokens": 0, "output_tokens": 0, "requests": 1}}
    inputs = {"inputs": [{"source": f"run-{n}", "claims": [claim], "pairs": []} for n in (1, 2)]}
    (tmp_path / "evals" / "judge_inputs").mkdir()
    (tmp_path / "evals" / "judge_inputs" / "judge-q1.json").write_text(json.dumps(inputs), encoding="utf-8")
    monkeypatch.setattr(
        composition, "build_judge_eval_runner",
        lambda settings: RunJudgeEvals(lambda _case: FakeJudge(CallLog(), "https://a.example/"), FakeClock()),
    )

    assert run_eval("--case", "judge-q1") == 0
    out = capsys.readouterr().out
    assert "2 份判决输入 × 1 次  最多 2 次" in out
    assert "输入取自 run-1" in out and "输入取自 run-2" in out
    assert "通过 1/1 道题" in out


def test_report_shows_the_day_told_to_the_model_and_who_produced_each_step(env, capsys):
    run, _, _ = env
    run("verify", "--question", "q1", "--mode", "cached")
    out = capsys.readouterr().out
    assert "告诉模型的今天：2026-09-12    模式：cached" in out
    assert "judge     模型 fake-judge  prompt fake-j1" in out
