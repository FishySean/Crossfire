"""summarize_run：仪表盘摘要的确定性规则。前端只渲染，不在这里做判断。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crossfire.application.summarize import headline_for, summarize_run, summary_to_dict
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
    SourceRuling,
    SourceRulingKind,
    SourceType,
    StepStats,
    Tier,
    Usage,
)

FIXTURES = Path(__file__).parent / "fixtures" / "runs"
USAGE = Usage(1, 1, 1)
STARTED = datetime(2026, 11, 22, 2, 43, 22, tzinfo=UTC)


def _result(
    *,
    sources: list[Source],
    claims: list[Claim] | None = None,
    pairs: list[Pair] | None = None,
    judgment: Judgment,
    pages: list[Page] | None = None,
) -> RunResult:
    if pages is None:
        pages = [
            Page(url=s.url, ok=True, title="t", markdown="正文 " + "段落。" * 80, status_code=200)
            for s in sources
        ]
    if claims is None:
        claims = [
            Claim(
                s.url,
                s.tier,
                f"claim for {s.url}",
                "e",
                SourceType.OTHER,
                None,
                0.9,
                USAGE,
                key_value="v1",
            )
            for s in sources
        ]
    return RunResult(
        question=Question(id="q", text="问题？", sources=tuple(sources)),
        mode=Mode.LIVE,
        started_at=STARTED,
        as_of=STARTED.date(),
        elapsed_seconds=1.0,
        steps={"fetch": StepStats(calls=len(sources), seconds=0.1)},
        provenance=None,
        pages=tuple(pages),
        claims=tuple(claims),
        pairs=tuple(pairs or ()),
        judgment=judgment,
    )


@pytest.mark.parametrize(
    ("wrong", "trusted", "scope", "failed", "kind"),
    [
        (0, 4, 0, False, "consistent"),
        (0, 4, 2, False, "consistent"),
        (1, 4, 0, False, "mostly_one"),
        (2, 4, 0, False, "mostly_many"),
        (3, 2, 0, False, "divided"),
        (0, 0, 0, True, "no_verdict"),
    ],
)
def test_headline_rules(wrong, trusted, scope, failed, kind):
    got_kind, zh, en = headline_for(wrong=wrong, trusted=trusted, scope=scope, judge_failed=failed)
    assert got_kind == kind
    assert zh and en
    if kind == "mostly_many":
        assert str(wrong) in zh and str(wrong) in en


def test_fallback_without_rulings_uses_trusted_sources_only():
    sources = [
        Source("https://a.example/", Tier.PRIMARY),
        Source("https://b.example/", Tier.NEWS),
        Source("https://c.example/", Tier.AGGREGATOR),
    ]
    judgment = Judgment(
        answer="ok",
        confidence=0.9,
        reasoning="r",
        conflicts=(),
        trusted_sources=("https://a.example/",),
        usage=USAGE,
        source_rulings=None,
    )
    # NLI 矛盾很多也不该把 b/c 标成 wrong
    pairs = [
        Pair("https://a.example/", "https://b.example/", Relation.CONTRADICT, "x", USAGE, scores={"contradict": 0.99}),
        Pair("https://a.example/", "https://c.example/", Relation.CONTRADICT, "x", USAGE, scores={"contradict": 0.2}),
    ]
    summary = summarize_run(_result(sources=sources, pairs=pairs, judgment=judgment))
    by_url = {row.url: row.status for row in summary.sources}
    assert by_url["https://a.example/"] == "trusted"
    assert by_url["https://b.example/"] == "neutral"
    assert by_url["https://c.example/"] == "neutral"
    assert summary.wrong_or_outdated_count == 0
    assert summary.headline_kind == "consistent"
    assert summary.nli_contradict_pairs == 2
    assert summary.nli_contradict_low_confidence == 1


def test_rulings_drive_status_and_mostly_one_headline():
    sources = [
        Source("https://good.example/", Tier.PRIMARY),
        Source("https://old.example/", Tier.NEWS),
        Source("https://scope.example/", Tier.AGGREGATOR),
    ]
    rulings = (
        SourceRuling("https://good.example/", SourceRulingKind.TRUSTED, "primary"),
        SourceRuling("https://old.example/", SourceRulingKind.OUTDATED, "stale"),
        SourceRuling("https://scope.example/", SourceRulingKind.SCOPE, "definition"),
    )
    judgment = Judgment(
        "ans",
        0.9,
        "r",
        (),
        ("https://good.example/",),
        USAGE,
        source_rulings=rulings,
    )
    pairs = [
        Pair(
            "https://old.example/",
            "https://good.example/",
            Relation.CONTRADICT,
            "stale",
            USAGE,
            scores={"contradict": 0.9},
        ),
        Pair(
            "https://old.example/",
            "https://scope.example/",
            Relation.CONTRADICT,
            "stale",
            USAGE,
            scores={"contradict": 0.8},
        ),
    ]
    summary = summarize_run(_result(sources=sources, pairs=pairs, judgment=judgment))
    assert summary.headline_kind == "mostly_one"
    assert "1" in summary.headline_zh
    assert summary.wrong_or_outdated_count == 1
    assert summary.scope_source_count == 1
    assert len(summary.conflict_groups) == 1
    assert summary.conflict_groups[0].focus_domain == "old.example"
    assert len(summary.conflict_groups[0].against_urls) == 2


def test_judge_failure_is_loud_no_verdict():
    from crossfire.domain import Failure

    sources = [Source("https://a.example/", Tier.PRIMARY)]
    judgment = Judgment(
        None,
        None,
        None,
        (),
        (),
        USAGE,
        failure=Failure(step="judge", detail="boom", raw=None),
    )
    summary = summarize_run(_result(sources=sources, judgment=judgment))
    assert summary.headline_kind == "no_verdict"
    assert summary.headline_zh == "没有结论"


def test_fetch_failure_marks_failed_node():
    sources = [
        Source("https://ok.example/", Tier.PRIMARY),
        Source("https://bad.example/", Tier.NEWS),
    ]
    pages = [
        Page(url="https://ok.example/", ok=True, title="t", markdown="正文 " + "段落。" * 80, status_code=200),
        Page(url="https://bad.example/", ok=False, error="403", status_code=403),
    ]
    claims = [
        Claim("https://ok.example/", Tier.PRIMARY, "1.0", "e", SourceType.OTHER, None, 0.9, USAGE),
        Claim(
            "https://bad.example/",
            Tier.NEWS,
            None,
            None,
            None,
            None,
            None,
            USAGE,
            failure=Failure(step="extract", detail="no page", raw=None),
        ),
    ]
    judgment = Judgment("a", 0.5, "r", (), ("https://ok.example/",), USAGE)
    summary = summarize_run(_result(sources=sources, claims=claims, pages=pages, judgment=judgment))
    by_url = {row.url: row.status for row in summary.sources}
    assert by_url["https://bad.example/"] == "failed"


def test_nodejs_fixture_with_rulings_groups_privatedevops():
    data = json.loads((FIXTURES / "nodejs-ask-with-rulings.json").read_text(encoding="utf-8"))
    summary = summarize_run(RunResult.from_dict(data))
    assert summary.headline_kind == "mostly_one"
    assert "大体一致" in summary.headline_zh
    assert summary.wrong_or_outdated_count == 1
    domains = [g.focus_domain for g in summary.conflict_groups]
    assert domains == ["privatedevops.com"]
    assert "privatedevops.com 与" in summary.conflict_groups[0].label_zh
    body = summary_to_dict(RunResult.from_dict(data))
    assert body["counts"]["faulty_sources"] == 1
    assert body["counts"]["pairs"] == len(data["pairs"])


def test_nodejs_fixture_old_record_fallback():
    data = json.loads((FIXTURES / "nodejs-ask-old.json").read_text(encoding="utf-8"))
    assert "source_rulings" not in data["judgment"]
    summary = summarize_run(RunResult.from_dict(data))
    assert summary.wrong_or_outdated_count == 0
    assert summary.headline_kind == "consistent"
    assert any(row.status == "trusted" for row in summary.sources)
    assert all(row.status in {"trusted", "neutral", "failed"} for row in summary.sources)


def test_source_ruling_unknown_url_is_loud():
    from crossfire.domain import RunResult as RR

    data = json.loads((FIXTURES / "nodejs-ask-with-rulings.json").read_text(encoding="utf-8"))
    data["judgment"]["source_rulings"][0]["url"] = "https://evil.example/"
    with pytest.raises(ValueError, match="不在本题来源"):
        RR.from_dict(data)


def test_claim_key_value_optional_round_trip():
    claim = Claim(
        "https://a.example/",
        Tier.PRIMARY,
        "Node 26.13.1",
        "e",
        SourceType.OTHER,
        None,
        0.9,
        USAGE,
        key_value="v26.13.1",
    )
    assert Claim.from_dict(claim.to_dict()).key_value == "v26.13.1"
    old = Claim.from_dict(
        {
            "url": "https://a.example/",
            "tier": "primary",
            "claim": "x",
            "evidence": "e",
            "source_type": "other",
            "confidence": 0.9,
            "published_date": None,
            "usage": {"input_tokens": 1, "output_tokens": 1, "requests": 1},
        }
    )
    assert old.key_value is None
