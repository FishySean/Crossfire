"""domain 层的纯单元测试：不联网、不写文件，只读 tests/fixtures/pages 下的快照。

usability 的预期结果不是按「应该怎样」写的，而是用搬家前 steel_client.is_usable_page
在同样输入上实际跑出来的结果。这一组测试的用途是证明搬家没有改变行为。
标着「锁住现状」的几条看起来不对，已登记在 notes/refactor-backlog.md，要改就连测试一起改。
"""

import ast
import json
import sys
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path

import pytest

from crossfire.domain import (
    Claim,
    Judgment,
    Mode,
    Page,
    Pair,
    Question,
    Relation,
    RunResult,
    Source,
    SourceType,
    Tier,
    UnknownSourceError,
    UnusableReason,
    is_usable_page,
)
from crossfire.extract import EXTRACT_SCHEMA
from crossfire.reconcile import PAIR_SCHEMA

DOMAIN_DIR = Path(__file__).resolve().parents[1] / "crossfire" / "domain"
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pages"

BEFORE_MOVE = {
    "bad_britannica_softblock": (False, UnusableReason.TOO_SHORT),
    "bad_space_nav_skeleton": (False, UnusableReason.NAV_SKELETON),
    "bad_thenewstack_page_not_found": (False, UnusableReason.ERROR_TITLE),
    "bad_theregister_404_title": (False, UnusableReason.ERROR_TITLE),
    "good_devguide_python_org_versions": (True, None),
    "good_en_wikipedia_org_wiki_planet": (True, None),
    "good_realpython_com_python313_new_features": (True, None),
    "good_science_nasa_gov_dwarf_planets_pluto": (True, None),
    "good_science_nasa_gov_solar_system_planets": (True, None),
    "good_www_python_org_downloads": (True, None),
    "good_www_w3schools_com_python_python_intro_asp": (True, None),
}

PROSE_LINE = "This sentence is ordinary article prose that is long enough to count here.\n"
ARTICLE = PROSE_LINE * 20


def page(markdown, title="Article", ok=True):
    return Page(url="https://example.com/", ok=ok, title=title, markdown=markdown)


# ---- 铁律：domain 只依赖标准库 ----


def test_domain_imports_only_the_standard_library():
    offenders = []
    for path in sorted(DOMAIN_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                top = module.split(".")[0]
                if module.startswith("crossfire.domain") or top in sys.stdlib_module_names:
                    continue
                offenders.append(f"{path.name}: {module}")
    assert offenders == []


# ---- usability：搬家前后行为一致 ----


def test_before_move_table_covers_every_fixture():
    assert {path.stem for path in FIXTURE_DIR.glob("*.json")} == set(BEFORE_MOVE)


@pytest.mark.parametrize(("name", "expected"), sorted(BEFORE_MOVE.items()))
def test_fixture_verdicts_match_before_move(name, expected):
    data = json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    assert is_usable_page(Page.from_dict(data)) == expected


@pytest.mark.parametrize(
    ("label", "subject", "expected"),
    [
        ("fetch failed", page(None, title=None, ok=False), (False, UnusableReason.FETCH_FAILED)),
        ("whitespace only", page("   \n  "), (False, UnusableReason.EMPTY)),
        ("title wins over length", page(ARTICLE, title="Page Not Found"), (False, UnusableReason.ERROR_TITLE)),
        ("title match ignores case", page(ARTICLE, title="ACCESS DENIED"), (False, UnusableReason.ERROR_TITLE)),
        ("499 chars", page("a" * 499), (False, UnusableReason.TOO_SHORT)),
        ("600 chars of prose", page("a" * 600), (True, None)),
        ("599 chars of prose", page("a" * 599), (False, UnusableReason.NAV_SKELETON)),
        ("59-char lines are not prose", page(("- " + "b" * 57 + "\n") * 30), (False, UnusableReason.NAV_SKELETON)),
        ("60-char lines are prose", page(("b" * 60 + "\n") * 10), (True, None)),
        ("link-dominated page", page(ARTICLE + "[" + "n" * 9000 + "](/x)\n"), (False, UnusableReason.NAV_SKELETON)),
        ("links below ratio", page(ARTICLE + "[" + "n" * 500 + "](/x)\n"), (True, None)),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_threshold_boundaries_match_before_move(label, subject, expected):
    assert is_usable_page(subject) == expected


def test_locked_reason_for_short_page_without_links_is_nav_skeleton():
    """锁住现状：500–599 字、一个链接都没有的页面，原因是 nav_skeleton 而不是 too_short。
    MIN_PROSE_CHARS=600 比 MIN_CONTENT_CHARS=500 更严，把这个区间吃掉了。"""
    assert is_usable_page(page("a" * 550)) == (False, UnusableReason.NAV_SKELETON)


@pytest.mark.parametrize("title", ["403(b) retirement plan limits", "Highway 404 closure", "Lost and not found"])
def test_locked_error_title_is_a_substring_match(title):
    """锁住现状：错误标题按子串匹配，标题里带 403 / 404 / not found 的正常文章也会被判废。"""
    assert is_usable_page(page(ARTICLE, title=title)) == (False, UnusableReason.ERROR_TITLE)


def test_locked_short_cjk_lines_are_not_prose():
    """锁住现状：每行 30 个汉字已是完整的中文句子，但不到 60 字符就不算正文，1200 字的中文页被判为骨架。"""
    markdown = "东京都的人口约为一千四百万人，这是二零二五年的最新统计数据。\n" * 40
    assert is_usable_page(page(markdown)) == (False, UnusableReason.NAV_SKELETON)


def test_status_code_does_not_affect_usability():
    assert is_usable_page(Page(url="https://example.com/", ok=True, title="Article", markdown=ARTICLE, status_code=404)) == (
        True,
        None,
    )


def test_unusable_reason_values_are_the_recorded_strings():
    assert [reason.value for reason in UnusableReason] == [
        "fetch_failed",
        "empty_content",
        "too_short",
        "error_page_title",
        "nav_skeleton",
    ]


# ---- 枚举值是对外契约 ----


def test_relation_values_match_pair_schema_verbatim():
    assert [relation.value for relation in Relation] == PAIR_SCHEMA["properties"]["relation"]["enum"]


def test_source_type_values_match_extract_schema_verbatim():
    assert [kind.value for kind in SourceType] == EXTRACT_SCHEMA["properties"]["source_type"]["enum"]


def test_unknown_relation_is_rejected_not_passed_through():
    data = {"a": "x", "b": "y", "relation": "disagree", "nature": "n", "usage": {"input_tokens": 1, "output_tokens": 1}}
    with pytest.raises(ValueError):
        Pair.from_dict(data)


# ---- Question.index_of ----

QUESTION = Question(
    id="q",
    text="?",
    sources=(
        Source("https://a.example/", Tier.PRIMARY),
        Source("https://b.example/", Tier.NEWS),
        Source("https://c.example/", Tier.AGGREGATOR),
    ),
)


def test_index_of_is_the_position_in_sources():
    assert [QUESTION.index_of(source.url) for source in QUESTION.sources] == [0, 1, 2]


def test_index_of_unknown_url_raises():
    with pytest.raises(UnknownSourceError):
        QUESTION.index_of("https://not-a-source.example/")


def test_index_of_does_not_normalise_urls():
    with pytest.raises(UnknownSourceError):
        QUESTION.index_of("https://a.example")


def test_duplicate_source_urls_are_rejected():
    with pytest.raises(ValueError, match="重复"):
        Question(id="q", text="?", sources=(Source("https://a.example/", Tier.PRIMARY),) * 2)


def test_entities_are_immutable():
    with pytest.raises(FrozenInstanceError):
        QUESTION.id = "other"


# ---- 序列化：键名和结构与现有结果文件逐字一致 ----

USAGE = {"input_tokens": 10, "output_tokens": 2}
FAILURE = {"step": "pair", "detail": "输出被 max_tokens=1000 截断", "raw": "[]"}
CLAIM = {
    "url": "https://a.example/",
    "tier": "primary",
    "claim": "3.14.7",
    "evidence": "Python 3.14.7",
    "source_type": "official_documentation",
    "confidence": 0.95,
    "published_date": "2026-09-01",
    "usage": USAGE,
}
FAILED_CLAIM = {
    "url": "https://b.example/",
    "tier": "news",
    "claim": None,
    "evidence": None,
    "source_type": None,
    "confidence": None,
    "published_date": None,
    "usage": USAGE,
    "failure": {**FAILURE, "step": "extract"},
}
PAIR = {"a": "https://a.example/", "b": "https://c.example/", "relation": "agree", "nature": "粒度不同", "usage": USAGE}
FAILED_PAIR = {**PAIR, "relation": None, "nature": None, "failure": FAILURE}
JUDGMENT = {
    "answer": "3.14.7",
    "confidence": 0.9,
    "reasoning": "一手源",
    "conflicts": [],
    "trusted_sources": ["https://a.example/"],
    "usage": USAGE,
}
PAGE = {
    "url": "https://a.example/",
    "ok": True,
    "title": "Python",
    "markdown": "body",
    "links": [{"text": "Docs", "url": "/docs"}],
    "error": None,
    "status_code": 200,
}
RUN = {
    "question_id": "q",
    "question": "?",
    "mode": "cached",
    "started_at": "2026-11-19T20:00:00.123456+00:00",
    "elapsed_seconds": 12.5,
    "sources": [{"url": s.url, "tier": s.tier.value} for s in QUESTION.sources],
    "pages_fetched": 2,
    "pages_failed": 1,
    "claude_calls": 4,
    "failures": [FAILED_CLAIM["failure"], FAILURE],
    "steps": {
        "fetch": {"calls": 3, "seconds": 1.0},
        "extract": {"calls": 2, "input_tokens": 20, "output_tokens": 4, "seconds": 2.0},
        "pair": {"calls": 1, "input_tokens": 10, "output_tokens": 2, "seconds": 3.0},
        "judge": {"calls": 1, "input_tokens": 10, "output_tokens": 2, "seconds": 4.0},
    },
    "total_input_tokens": 40,
    "total_output_tokens": 8,
    "pages": [PAGE, {**PAGE, "url": "https://b.example/"}, {**PAGE, "url": "https://c.example/", "ok": False}],
    "claims": [CLAIM, FAILED_CLAIM],
    "pairs": [FAILED_PAIR],
    "judgment": JUDGMENT,
}


@pytest.mark.parametrize(
    ("entity", "data"),
    [
        (Claim, CLAIM),
        (Claim, FAILED_CLAIM),
        (Pair, PAIR),
        (Pair, FAILED_PAIR),
        (Judgment, JUDGMENT),
        (Page, PAGE),
        (RunResult, RUN),
    ],
    ids=["claim", "failed-claim", "pair", "failed-pair", "judgment", "page", "run"],
)
def test_round_trip_preserves_keys_order_and_values(entity, data):
    out = entity.from_dict(data).to_dict()
    assert out == data
    assert list(out) == list(data)


def test_conflicts_encoded_as_a_string_are_rejected_not_split_into_characters():
    """out/runs/tokyo-population_20260912T224644Z.json 里真实出现过：模型把数组编码成字符串返回。"""
    with pytest.raises(TypeError, match="conflicts"):
        Judgment.from_dict({**JUDGMENT, "conflicts": '["口径差异"]'})


def test_no_failure_key_when_nothing_failed():
    assert "failure" not in Claim.from_dict(CLAIM).to_dict()


def test_unanswered_and_failed_claims_look_the_same_except_for_failure():
    """锁住现状：text 为 None 既可能是「没回答」也可能是「提取失败」，只能靠 failure 区分。"""
    unanswered = Claim.from_dict({**CLAIM, "claim": None, "evidence": None})
    failed = Claim.from_dict(FAILED_CLAIM)
    assert not unanswered.answered and not failed.answered
    assert unanswered.failure is None and failed.failure is not None


def test_run_result_derived_fields():
    run = RunResult.from_dict(RUN)
    assert run.mode is Mode.CACHED
    assert run.started_at == datetime(2026, 11, 19, 20, 0, 0, 123456, tzinfo=timezone.utc)
    assert (run.pages_fetched, run.pages_failed) == (2, 1)
    assert run.total_input_tokens == 40


def test_locked_failures_exclude_fetch_failures():
    """锁住现状：有一页抓取失败，failures 里却只有 LLM 的失败。backlog 最高优先级那条。"""
    run = RunResult.from_dict(RUN)
    assert run.pages_failed == 1
    assert {failure.step for failure in run.failures} == {"extract", "pair"}


def test_locked_claude_calls_ignores_retries():
    """锁住现状：claude_calls 只是条数之和加一，不含任何重试。"""
    assert RunResult.from_dict(RUN).claude_calls == len(RUN["claims"]) + len(RUN["pairs"]) + 1
