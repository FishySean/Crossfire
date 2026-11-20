"""题库提示剥离、按题切分、agreement 规则。"""

from datetime import UTC, date, datetime

import pytest

from crossfire.adapters.anthropic.extractor import EXTRACT_PROMPT
from crossfire.adapters.anthropic.judge import JUDGE_PROMPT
from crossfire.adapters.anthropic.pairer import PAIR_PROMPT
from crossfire.application.use_cases.export_dataset import (
    EVAL_OVERLAP_IDS,
    export_pair_dataset,
    split_question_ids,
)
from crossfire.domain import (
    BankQuestion,
    Claim,
    Judgment,
    KeptSource,
    Mode,
    Pair,
    QuestionCategory,
    Relation,
    RunResult,
    Source,
    StepStats,
    Tier,
    Usage,
    question_text_hint_reason,
)


def test_hint_detector_catches_scope_and_reprint_leaks():
    assert question_text_hint_reason("上海的人口是多少？（常住人口 vs 户籍人口口径不同，数字有差异）")
    assert question_text_hint_reason("泰坦尼克号沉没于哪一年？（部分转载文章错误写为 1911 年）")
    assert question_text_hint_reason("NBA currently has how many teams — 30 or 32?")
    assert question_text_hint_reason("Node.js 当前的 LTS（长期支持）稳定版本号是多少？") is None
    assert question_text_hint_reason("伦敦的人口是多少？") is None


def test_design_note_never_appears_in_pipeline_prompts_or_question_text():
    # 变异目标：如果 design_note 被拼进 prompt 模板，这里会红。
    note = "设计意图：常住 vs 户籍，绝不能进 prompt"
    question = BankQuestion(
        id="shanghai-population-scope",
        text="上海的人口是多少？",
        category=QuestionCategory.SCOPE,
        language="zh",
        generated_on=date(2026, 11, 20),
        keywords=("上海", "人口"),
        sources=(KeptSource(Source("https://a.example", Tier.PRIMARY), "t", "q"),),
        rejected=(),
        design_note=note,
    )
    pipeline = question.to_pipeline_question()
    assert note not in pipeline.text
    assert not hasattr(pipeline, "design_note")
    for template in (EXTRACT_PROMPT, PAIR_PROMPT, JUDGE_PROMPT):
        assert "design_note" not in template
        # 模板里只有 {question} 占位，没有 design_note；渲染时只喂 pipeline.text。
        assert "{question}" in template
        assert note not in template.format_map(
            _SafeMap(as_of="2026-11-20", question=pipeline.text, url="u", title="t", content="c")
        )


class _SafeMap(dict):
    """缺的 format 键返回空串，方便只检查 question 相关泄漏。"""

    def __missing__(self, key: str) -> str:
        return ""


def test_split_keeps_whole_question_together_and_holds_out_eval_overlap():
    ids = [
        "python-latest-stable",
        "nodejs-lts-version",
        "shanghai-population-scope",
        "amazon-employee-count-scope",
        "bitcoin-creator-reprint",
        "eiffel-tower-height",
        "ubuntu-lts-version",
        "london-population-scope",
        "titanic-sinking-year-reprint",
        "apple-ceo-current",
    ]
    split = split_question_ids(ids, seed="test-seed", train_ratio=0.8)
    assert set(split.train_ids).isdisjoint(set(split.test_ids))
    assert EVAL_OVERLAP_IDS <= set(split.test_ids)
    assert set(split.train_ids).isdisjoint(EVAL_OVERLAP_IDS)


def test_single_vote_agreement_is_null_not_one():
    bank = [
        BankQuestion(
            id="q1",
            text="伦敦的人口是多少？",
            category=QuestionCategory.SCOPE,
            language="zh",
            generated_on=date(2026, 11, 20),
            keywords=("伦敦", "人口"),
            sources=(
                KeptSource(Source("https://a.example", Tier.PRIMARY), "a", "q"),
                KeptSource(Source("https://b.example", Tier.NEWS), "b", "q"),
            ),
            rejected=(),
        )
    ]
    run = RunResult(
        question=bank[0].to_pipeline_question(),
        mode=Mode.CACHED,
        started_at=datetime(2026, 11, 20, tzinfo=UTC),
        as_of=date(2026, 11, 20),
        elapsed_seconds=1.0,
        steps={"extract": StepStats(1, 0.1, 1, 1, 1)},
        provenance=None,
        pages=(),
        claims=(
            Claim("https://a.example", Tier.PRIMARY, "900万", "e", None, None, 0.9, Usage(1, 1, 1)),
            Claim("https://b.example", Tier.NEWS, "1400万", "e", None, None, 0.8, Usage(1, 1, 1)),
        ),
        pairs=(Pair("https://a.example", "https://b.example", Relation.SAME_QUESTION_DIFFERENT_SCOPE, "口径", Usage(1, 1, 1)),),
        judgment=Judgment("看口径", 0.5, "r", (), (), Usage(1, 1, 1)),
    )
    export = export_pair_dataset(bank, {"q1": run}, seed="s")
    assert len(export.examples) == 1
    assert export.examples[0].agreement is None
    assert len(export.examples[0].votes) == 1
