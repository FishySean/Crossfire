"""评测集：判分规则、标准答案的依据、冻结快照。全部离线，不调模型。"""

import json
from datetime import date

import pytest

from crossfire.adapters.steel import CachedPageFetcher
from crossfire.application.use_cases import RunEvals, estimate_requests
from crossfire.composition import assemble
from crossfire.config import Settings, eval_snapshot_dir, load_eval_cases, load_questions
from crossfire.domain import Mode, Question
from crossfire.domain.evals import (
    EvalCase,
    FigureInRange,
    FigureNeedsContext,
    Forbids,
    LeadsWith,
    figures,
    rule_from_dict,
    sentence_around,
)
from tests.fakes import CallLog, FakeExtractor, FakeFetcher, FakePairer, FakeJudge

SETTINGS = Settings.from_mapping({})
CASES = {case.id: case for case in load_eval_cases(SETTINGS)}
QUESTIONS = {question.id: question for question in load_questions(SETTINGS)}

# 真实出现过的错误答案，只当反例用，不参与定标准答案。
WRONG_ANSWERS = {
    "python-2026-11": [
        # out/runs/python-latest-version_20261119T230333Z.json，第 4 步 live 运行的原话。
        "根据 Python 官方下载页（python.org/downloads/），Python 目前最新的稳定版本是 **Python 3.13.x**"
        "（截至本次查证信息，3.13 于 2024-10-07 正式发布）。注意：来源中提到的 3.15.2 存疑，该版本号超出当前"
        "已知发布序列，很可能是预发布/开发版被误标为稳定版，建议以 python.org 官网实时显示为准。",
        "Python 目前的最新稳定版本是 **Python 3.14.7**，由 python.org 官方下载页直接提供。",
        "最新稳定版是 3.15.2，但该版本存疑，可能是预发布版。",
    ],
    "python-2026-09": [
        "Python 目前最新的稳定版本是 Python 3.13，3.14.7 也已发布。",
        "最新稳定版是 3.15.2。",
    ],
    "nodejs-2026-09": [
        "Node.js 目前处于 Active LTS 的版本是 v22（Jod），v24 将于 2025-10-28 进入 Active LTS。",
        "截至 2026-09-12，Active LTS 是 Node.js 26。",
    ],
    "tokyo-2026-09": [
        "东京人口约为3,700万人，其中东京都约1,430万人。",
        "东京都人口约 1,405 万人（2020 年普查）。",
        "东京约有 37 million 人。",
    ],
}

# 写法不同但都对的答案：规则不能误杀。
RIGHT_ANSWERS = {
    "python-2026-11": [
        "截至 2026-11-19，Python 最新稳定版本是 **3.15.2**；3.15 分支于 2026-10-09 首发，处于 bugfix 阶段。",
        "Python 3.15.2 是目前最新的稳定版（3.14 仍在 bugfix，3.13 已进入 security）。",
    ],
    "python-2026-09": [
        "Python 目前的最新稳定版本是 **Python 3.14.7**，3.13 系列同样处于积极维护（bugfix）状态。",
    ],
    "nodejs-2026-09": [
        "Node.js 目前处于 Active LTS 的版本是 **v24（代号 Krypton）**，持续至 2026-10-20；v22 已降为 Maintenance LTS。",
        "目前处于 Active LTS 的是 Node.js 24（Krypton）。",
        "截至当前（2026年），处于 Active LTS 的版本是v24。",
    ],
    "tokyo-2026-09": [
        "东京都（行政区划）的人口约为1,430万人；若指大东京都市圈（Greater Tokyo Area），则人口约为3,700万人"
        "（联合国2026年估计约3,695万）。",
        "东京的人口因口径不同有两个答案：①东京都：14,246,219人（2025年普查速报）；②大东京都市圈：约36,954,512人。",
        "Tokyo Metropolis has about 14.3 million people.",
    ],
}


def test_the_four_cases_exist():
    assert sorted(CASES) == ["nodejs-2026-09", "python-2026-09", "python-2026-11", "tokyo-2026-09"]


@pytest.mark.parametrize("case_id", sorted(WRONG_ANSWERS))
def test_known_wrong_answers_fail(case_id):
    for answer in WRONG_ANSWERS[case_id]:
        grade = CASES[case_id].grade(answer)
        assert not grade.passed, answer
        assert grade.reasons


@pytest.mark.parametrize("case_id", sorted(RIGHT_ANSWERS))
def test_right_answers_in_other_wordings_pass(case_id):
    for answer in RIGHT_ANSWERS[case_id]:
        grade = CASES[case_id].grade(answer)
        assert grade.passed, (answer, grade.reasons)


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_gold_answer_passes_its_own_rules(case_id):
    assert CASES[case_id].grade(CASES[case_id].gold_answer).passed


def test_no_answer_fails():
    assert not CASES["python-2026-11"].grade(None).passed
    assert not CASES["python-2026-11"].grade("").passed


# ---- 依据和快照：标准答案必须站在冻结页面的原文上 ----


def snapshot_pages(case: EvalCase):
    question = QUESTIONS[case.question_id]
    return question, CachedPageFetcher(eval_snapshot_dir(SETTINGS, case)).fetch_all([s.url for s in question.sources])


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_snapshot_covers_every_source_and_every_page_is_usable(case_id):
    _, pages = snapshot_pages(CASES[case_id])
    assert all(page.ok and page.usable for page in pages), [(p.url, p.unusable_reason) for p in pages]
    assert len(list(eval_snapshot_dir(SETTINGS, CASES[case_id]).glob("*.json"))) == len(pages)


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_snapshot_was_fetched_on_the_as_of_day(case_id):
    case = CASES[case_id]
    _, pages = snapshot_pages(case)
    assert {page.fetched_at.date() for page in pages if page.fetched_at} == {case.as_of}
    assert all(page.fetched_at is not None for page in pages)


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_every_evidence_quote_appears_verbatim_in_the_snapshot(case_id):
    case = CASES[case_id]
    _, pages = snapshot_pages(case)
    by_url = {page.url: page.markdown or "" for page in pages}
    for evidence in case.evidence:
        assert evidence.quote in by_url[evidence.url], (evidence.url, evidence.quote)


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_snapshot_pages_record_where_their_fetch_time_came_from(case_id):
    for path in eval_snapshot_dir(SETTINGS, CASES[case_id]).glob("*.json"):
        assert json.loads(path.read_text(encoding="utf-8"))["fetched_at_basis"]


# ---- 规则 ----


def test_leads_with_rejects_a_competitor_that_comes_first():
    rule = LeadsWith(expected=r"3\.15\.2", competitors=(r"3\.13",), why="-")
    assert rule.check("3.15.2，3.13 是旧的") is None
    assert "3.13" in (rule.check("3.13，另有 3.15.2") or "")
    assert "没有标准答案" in (rule.check("3.14") or "")


def test_forbids():
    assert Forbids(pattern="存疑", why="-").check("3.15.2 存疑") is not None
    assert Forbids(pattern="存疑", why="-").check("3.15.2") is None


@pytest.mark.parametrize(
    ("text", "values"),
    [
        ("约1,430万人", [14_300_000]),
        ("14,303,513人", [14_303_513]),
        ("约 3,700 万", [37_000_000]),
        ("1430.4万", [14_304_000]),
        ("14.3 million", [14_300_000]),
        ("2026年8月，第 3 名", []),
    ],
)
def test_figures(text, values):
    assert [figure.value for figure in figures(text)] == values


def test_sentence_around_does_not_break_on_commas():
    text = "东京都约1,430万人；若指大东京都市圈（含周边），人口约为3,700万人。其余"
    position = text.index("3,700")
    assert sentence_around(text, position) == "若指大东京都市圈（含周边），人口约为3,700万人"


def test_figure_rules():
    in_range = FigureInRange(low=14_200_000, high=14_399_999, why="-")
    assert in_range.check("1,425万") is None and in_range.check("1,405万") is not None
    context = FigureNeedsContext(low=36_000_000, high=39_000_000, context="都市圈", why="-")
    assert context.check("东京都市圈约3,700万人") is None
    assert context.check("东京人口约3,700万人。都市圈") is not None


def test_every_rule_needs_a_reason():
    with pytest.raises(ValueError, match="why"):
        rule_from_dict({"kind": "forbids", "pattern": "x"})
    with pytest.raises(ValueError, match="不认识"):
        rule_from_dict({"kind": "llm_judge", "why": "-"})


# ---- 跑评测：重复几次、按规则判、估算请求数 ----


def test_estimate_is_an_upper_bound_per_repeat():
    case, question = CASES["python-2026-11"], QUESTIONS["python-latest-version"]
    assert estimate_requests(case, question) == (4 + 6 + 1) * 3


def test_a_case_passes_only_if_every_repeat_passes(tmp_path):
    case = CASES["python-2026-11"]
    question = QUESTIONS[case.question_id]
    answers = iter(["最新稳定版是 3.15.2。", "最新稳定版是 3.13.x，3.15.2 存疑。", "3.15.2"])

    class ScriptedJudge(FakeJudge):
        def judge(self, *args, **kwargs):
            judgment = super().judge(*args, **kwargs)
            return type(judgment)(**{**judgment.__dict__, "answer": next(answers)})

    log = CallLog()

    def verifier_for(_case, _question):
        return assemble(
            fetcher=FakeFetcher(mode=Mode.CACHED),
            extractor=FakeExtractor(log),
            pairer=FakePairer(log),
            judge=ScriptedJudge(log, question.sources[0].url),
            runs_dir=tmp_path,
        )

    outcome = RunEvals(verifier_for).execute(case, question)
    assert [attempt.grade.passed for attempt in outcome.attempts] == [True, False, True]
    assert not outcome.passed
    assert len(list(tmp_path.glob("*.json"))) == 3


def test_case_and_question_must_match():
    case = CASES["python-2026-11"]
    other = Question.from_dict({"id": "x", "question": "?", "sources": []})
    with pytest.raises(ValueError, match="python-latest-version"):
        RunEvals(lambda *_: None).execute(case, other)  # type: ignore[arg-type]


def test_case_file_name_must_match_its_id(tmp_path):
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "wrong-name.yaml").write_text(
        (SETTINGS.evals_dir / "cases" / "python-2026-11.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    settings = Settings.from_mapping({"CROSSFIRE_EVALS_DIR": str(tmp_path)})
    with pytest.raises(ValueError, match="文件名"):
        load_eval_cases(settings)


def test_as_of_is_a_date():
    assert CASES["python-2026-11"].as_of == date(2026, 11, 19)
