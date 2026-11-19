"""domain 层的纯单元测试：不联网、不写文件，只读 tests/fixtures/pages 下的快照。

usability 的预期结果不是按「应该怎样」写的，而是用搬家前 steel_client.is_usable_page
在同样输入上实际跑出来的结果。这一组测试的用途是证明搬家没有改变行为。
标着「锁住现状」的几条看起来不对，已登记在 notes/refactor-backlog.md，要改就连测试一起改。
"""

import ast
import dataclasses
import json
import sys
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path

import pytest

from crossfire.domain import (
    Claim,
    Failure,
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
from crossfire.adapters.anthropic.extractor import EXTRACT_SCHEMA
from crossfire.adapters.anthropic.pairer import PAIR_SCHEMA

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
        # 第 4 步有意修改：NAV_SKELETON → TOO_SHORT。原因：backlog「500–599 字无链接页判成 nav_skeleton」
        ("599 chars of prose", page("a" * 599), (False, UnusableReason.TOO_SHORT)),
        ("59-char lines are not prose", page(("- " + "b" * 57 + "\n") * 30), (False, UnusableReason.NAV_SKELETON)),
        ("60-char lines are prose", page(("b" * 60 + "\n") * 10), (True, None)),
        ("link-dominated page", page(ARTICLE + "[" + "n" * 9000 + "](/x)\n"), (False, UnusableReason.NAV_SKELETON)),
        ("links below ratio", page(ARTICLE + "[" + "n" * 500 + "](/x)\n"), (True, None)),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_threshold_boundaries_match_before_move(label, subject, expected):
    assert is_usable_page(subject) == expected


# ---- 第 4 步修掉的三处误杀。原来这里是三条「锁住现状」的测试，改成了相反的断言 ----


@pytest.mark.parametrize("length", [500, 550, 599])
def test_short_page_without_links_is_too_short_not_nav_skeleton(length):
    """第 4 步有意修改：原 test_locked_reason_for_short_page_without_links_is_nav_skeleton 断言 NAV_SKELETON。
    原因：一个链接都没有的短页面，缺的是篇幅，不是被导航挤掉了正文。"""
    assert is_usable_page(page("a" * length)) == (False, UnusableReason.TOO_SHORT)


def test_short_page_dominated_by_links_is_still_nav_skeleton():
    links = "".join(f"[菜单项{i:02d}](/n{i})\n" for i in range(60))
    assert is_usable_page(page(links + "a" * 50)) == (False, UnusableReason.NAV_SKELETON)


def test_long_list_without_prose_is_still_nav_skeleton():
    assert is_usable_page(page(("- " + "b" * 57 + "\n") * 30)) == (False, UnusableReason.NAV_SKELETON)


@pytest.mark.parametrize(
    "title",
    [
        "403(b) retirement plan limits",
        "Highway 404 closure",
        "Lost and not found",
        "Route 403 reopens - Local News",
        "Python 3.14.0 release notes | Python.org",
        "Just a moment of silence for the old API",
    ],
)
def test_article_titles_that_merely_contain_an_error_word_are_usable(title):
    """第 4 步有意修改：原 test_locked_error_title_is_a_substring_match 断言 ERROR_TITLE。
    原因：子串匹配把标题里带 403 / 404 / not found 的正常文章判成软 404。"""
    assert is_usable_page(page(ARTICLE, title=title)) == (True, None)


@pytest.mark.parametrize(
    "title",
    [
        "Page not found",
        "404 - The Register",
        "Page Not Found – The New Stack",
        "404",
        "404 Not Found",
        "403 Forbidden",
        "Error 404 (Not Found)",
        "HTTP 404 error",
        "Not Found",
        "Access Denied",
        "Attention Required! | Cloudflare",
        "Just a moment...",
        "Are you a robot?",
        "Oops | 404 page not found",
    ],
)
def test_real_error_titles_are_still_caught(title):
    assert is_usable_page(page(ARTICLE, title=title)) == (False, UnusableReason.ERROR_TITLE)


CJK_SENTENCE = "东京都的人口约为一千四百万人，这是二零二五年的最新统计数据。"


def test_cjk_sentences_count_as_prose():
    """第 4 步有意修改：原 test_locked_short_cjk_lines_are_not_prose 断言 NAV_SKELETON。
    原因：60 字符的行长门槛是按英文定的，30 个汉字已经是完整的中文句子。"""
    assert len(CJK_SENTENCE) == 30
    assert is_usable_page(page((CJK_SENTENCE + "\n") * 40)) == (True, None)


def test_japanese_sentences_count_as_prose():
    line = "令和七年国勢調査の速報値によると、東京都の人口は増加を続けています。\n"
    assert is_usable_page(page(line * 30)) == (True, None)


def test_short_cjk_menu_lines_are_still_not_prose():
    assert is_usable_page(page("- 新闻中心\n" * 300)) == (False, UnusableReason.NAV_SKELETON)


def test_locked_total_length_floor_still_counts_raw_characters():
    """锁住现状：总长下限 MIN_CONTENT_CHARS 仍按原始字符数算，没有按宽度。
    300 个汉字的信息量大约相当于 600 个英文字符，仍被判 too_short。这一步只修行长，这条留着。"""
    assert is_usable_page(page(CJK_SENTENCE * 10)) == (False, UnusableReason.TOO_SHORT)


def test_page_usability_is_computed_not_stored():
    good, bad = page(ARTICLE), page("a" * 550)
    assert (good.usable, good.unusable_reason) == (True, None)
    assert (bad.usable, bad.unusable_reason) == (False, UnusableReason.TOO_SHORT)
    assert "usable" not in {field.name for field in dataclasses.fields(Page)}
    assert "usable" not in bad.to_dict()


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        (page(ARTICLE), None),
        (Page(url="https://x/", ok=False, error="503 boom"), Failure("fetch", "503 boom", None)),
        (Page(url="https://x/", ok=False), Failure("fetch", "抓取失败，没有错误信息", None)),
        (page("a" * 550), Failure("usability", "too_short", None)),
        (page(ARTICLE, title="404 - The Register"), Failure("usability", "error_page_title", None)),
    ],
)
def test_page_failure_explains_why_a_page_was_not_extracted(subject, expected):
    assert subject.failure == expected


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

# requests 是第 3 步新加的键：实际发出的请求数。失败的记录都重试过一次，所以是 2。
USAGE = {"input_tokens": 10, "output_tokens": 2, "requests": 1}
RETRIED = {"input_tokens": 10, "output_tokens": 2, "requests": 2}
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
    "usage": RETRIED,
    "failure": {**FAILURE, "step": "extract"},
}
PAIR = {"a": "https://a.example/", "b": "https://c.example/", "relation": "agree", "nature": "粒度不同", "usage": USAGE}
FAILED_PAIR = {**PAIR, "relation": None, "nature": None, "usage": RETRIED, "failure": FAILURE}
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
    # 第 4 步改了测试数据（断言没改）："body" → 一篇够长的正文。原因：usable 接上之后，
    # 4 个字符的正文会被判 too_short 并进 failures，而这个样例的本意是「两页可用、一页抓取失败」。
    "markdown": ARTICLE,
    "links": [{"text": "Docs", "url": "/docs"}],
    "error": None,
    "status_code": 200,
}
FETCH_FAILURE = {"step": "fetch", "detail": "HTTP 503", "raw": None}
RUN = {
    "question_id": "q",
    "question": "?",
    "mode": "cached",
    "started_at": "2026-11-19T20:00:00.123456+00:00",
    "elapsed_seconds": 12.5,
    "sources": [{"url": s.url, "tier": s.tier.value} for s in QUESTION.sources],
    "pages_fetched": 2,
    "pages_failed": 1,
    "claude_calls": 6,
    "failures": [FETCH_FAILURE, FAILED_CLAIM["failure"], FAILURE],
    "steps": {
        "fetch": {"calls": 3, "seconds": 1.0},
        "extract": {"calls": 2, "input_tokens": 20, "output_tokens": 4, "seconds": 2.0, "requests": 3},
        "pair": {"calls": 1, "input_tokens": 10, "output_tokens": 2, "seconds": 3.0, "requests": 2},
        "judge": {"calls": 1, "input_tokens": 10, "output_tokens": 2, "seconds": 4.0, "requests": 1},
    },
    "total_input_tokens": 40,
    "total_output_tokens": 8,
    "pages": [
        PAGE,
        {**PAGE, "url": "https://b.example/"},
        {**PAGE, "url": "https://c.example/", "ok": False, "error": "HTTP 503"},
    ],
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


def test_failures_include_fetch_failures():
    run = RunResult.from_dict(RUN)
    assert run.pages_failed == 1
    # 第 3 步有意修改：failures 只有 LLM 的失败 {"extract", "pair"} → 抓取失败也以 step="fetch" 排在最前，
    # 原因：backlog「【最高优先级】抓取失败不进 failures」
    assert [failure.step for failure in run.failures] == ["fetch", "extract", "pair"]
    assert run.failures[0] == Failure(step="fetch", detail="HTTP 503", raw=None)


def test_every_failed_page_is_a_failure_even_without_an_error_message():
    pages = [{**PAGE, "url": url, "ok": False, "error": None} for url in ("https://a.example/", "https://b.example/")]
    run = RunResult.from_dict({**RUN, "pages": pages, "claims": [], "pairs": [], "judgment": JUDGMENT})
    assert [(f.step, f.raw) for f in run.failures] == [("fetch", None), ("fetch", None)]
    assert all(f.detail for f in run.failures)


def test_model_requests_counts_every_request_including_retries():
    # 第 3 步有意修改：claude_calls == 条数之和 + 1 → 各记录 usage.requests 之和（1 + 2 + 2 + 1），
    # 原因：backlog「claude_calls 少算重试」
    # 第 4 步有意修改：claude_calls → model_requests。原因：决定 3，代码里改名，JSON 键名不变
    assert RunResult.from_dict(RUN).model_requests == 6
    assert RunResult.from_dict(RUN).to_dict()["claude_calls"] == 6
    assert RunResult.from_dict(RUN).steps["extract"].requests == 3


@pytest.mark.parametrize(
    ("entity", "data", "key", "value"),
    [
        (Claim, CLAIM, "confidence", "0.9"),
        (Claim, CLAIM, "confidence", True),
        (Claim, CLAIM, "claim", 3.14),
        (Claim, CLAIM, "published_date", 20260901),
        (Judgment, JUDGMENT, "confidence", "0.9"),
        (Judgment, JUDGMENT, "answer", 1.0),
        (Pair, PAIR, "nature", ["粒度不同"]),
        (Page, PAGE, "ok", "true"),
        (Page, PAGE, "status_code", "200"),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_scalars_of_the_wrong_type_are_rejected(entity, data, key, value):
    with pytest.raises(TypeError, match=key):
        entity.from_dict({**data, key: value})


def test_usage_requests_must_be_an_integer():
    with pytest.raises(TypeError, match="requests"):
        Claim.from_dict({**CLAIM, "usage": {**USAGE, "requests": "1"}})
    with pytest.raises(KeyError):
        Claim.from_dict({**CLAIM, "usage": {"input_tokens": 10, "output_tokens": 2}})


def test_integer_confidence_is_kept_as_is():
    """真实结果文件里有整数 1 的 confidence。"""
    assert Claim.from_dict({**CLAIM, "confidence": 1}).to_dict()["confidence"] == 1
