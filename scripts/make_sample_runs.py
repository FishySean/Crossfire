"""Generate local sample result files for developing and checking the viewer (no external API calls).

The runs are built from domain entities and written with run_record, so they always match the
current result format and pass RunResult.from_dict. Pass --out to write somewhere other than out/runs.
"""

import argparse
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from crossfire.application.records import run_record
from crossfire.domain import (
    Claim,
    Failure,
    Judgment,
    Mode,
    Page,
    Pair,
    Provenance,
    Question,
    Relation,
    RunResult,
    Source,
    SourceType,
    StepStats,
    Tier,
    Usage,
)

RUNS_DIR = Path(__file__).resolve().parents[1] / "out" / "runs"

DOWNLOADS = Source("https://www.python.org/downloads/", Tier.PRIMARY)
DEVGUIDE = Source("https://devguide.python.org/versions/", Tier.PRIMARY)
REALPYTHON = Source("https://realpython.com/python313-new-features/", Tier.NEWS)
W3SCHOOLS = Source("https://www.w3schools.com/python/python_intro.asp", Tier.AGGREGATOR)
SOURCES = (DOWNLOADS, DEVGUIDE, REALPYTHON, W3SCHOOLS)

FETCHED_AT = datetime(2026, 9, 12, 20, 18, 0, tzinfo=UTC)
SAMPLE_TEXT = "This is sample page content used to exercise the result viewer without any network calls. " * 10
PROVENANCE = {
    "extract": Provenance(model="sample-model", prompt_version=None),
    "pair": Provenance(model="sample-model", prompt_version=None),
    "judge": Provenance(model="sample-model", prompt_version=None),
}


def usage(input_tokens: int, output_tokens: int) -> Usage:
    return Usage(input_tokens=input_tokens, output_tokens=output_tokens, requests=1)


def page(source: Source) -> Page:
    return Page(
        url=source.url,
        ok=True,
        title=source.url,
        markdown=f"# {source.url}\n\n{SAMPLE_TEXT}",
        status_code=200,
        fetched_at=FETCHED_AT,
    )


def claim(source: Source, text: str, evidence: str, source_type: SourceType, confidence: float, published: str | None) -> Claim:
    return Claim(
        source_url=source.url,
        tier=source.tier,
        text=text,
        evidence=evidence,
        source_type=source_type,
        published_date=published,
        confidence=confidence,
        usage=usage(4200, 180),
    )


def pair(a: Source, b: Source, relation: Relation, nature: str) -> Pair:
    return Pair(a_url=a.url, b_url=b.url, relation=relation, nature=nature, usage=usage(900, 90))


def steps(pages: tuple[Page, ...], claims: tuple[Claim, ...], pairs: tuple[Pair, ...], judgment: Judgment) -> dict[str, StepStats]:
    def stats(records: tuple[Claim, ...] | tuple[Pair, ...] | tuple[Judgment, ...], seconds: float) -> StepStats:
        return StepStats(
            calls=len(records),
            seconds=seconds,
            input_tokens=sum(record.usage.input_tokens for record in records),
            output_tokens=sum(record.usage.output_tokens for record in records),
            requests=sum(record.usage.requests or 0 for record in records),
        )

    return {
        "fetch": StepStats(calls=len(pages), seconds=6.2),
        "extract": stats(claims, 12.4),
        "pair": stats(pairs, 8.9),
        "judge": stats((judgment,), 14.2),
    }


def run(question: Question, started_at: datetime, pages: tuple[Page, ...], claims: tuple[Claim, ...], pairs: tuple[Pair, ...], judgment: Judgment) -> RunResult:
    return RunResult(
        question=question,
        mode=Mode.LIVE,
        started_at=started_at,
        as_of=started_at.date(),
        elapsed_seconds=41.7,
        steps=steps(pages, claims, pairs, judgment),
        provenance=PROVENANCE,
        pages=pages,
        claims=claims,
        pairs=pairs,
        judgment=judgment,
    )


def base_run() -> RunResult:
    question = Question(
        id="python-latest-version",
        text="Which Python version is currently the latest stable release?",
        sources=SOURCES,
    )
    claims = (
        claim(DOWNLOADS, "The latest stable Python release is 3.13.1.",
              "Download the latest version for Windows — Python 3.13.1", SourceType.OFFICIAL_DOCUMENTATION, 0.95, "2025-12-03"),
        claim(DEVGUIDE, "3.13 is the current bugfix branch, i.e. the latest stable release.",
              "3.13 bugfix security 2024-10-07 2029-10", SourceType.OFFICIAL_DOCUMENTATION, 0.92, "2025-11-20"),
        claim(REALPYTHON, "Python 3.13 has shipped and is the newest available release.",
              "Python 3.13 is now available with a new REPL and free-threaded mode", SourceType.NEWS_ARTICLE, 0.8, "2024-10-08"),
        claim(W3SCHOOLS, "The most recent major Python version is 3.11.",
              "The most recent major version of Python is Python 3", SourceType.ENCYCLOPEDIA, 0.6, None),
    )
    pairs = (
        pair(DOWNLOADS, DEVGUIDE, Relation.AGREE, "Both treat the 3.13 series as the current stable branch."),
        pair(DOWNLOADS, REALPYTHON, Relation.AGREE, "Both point at 3.13; only the patch-level granularity differs."),
        pair(DOWNLOADS, W3SCHOOLS, Relation.CONTRADICT,
             "Different numbers: python.org says 3.13.1 while w3schools still says 3.11 (stale page)."),
        pair(DEVGUIDE, REALPYTHON, Relation.AGREE, "Both agree 3.13 is the current bugfix branch."),
        pair(DEVGUIDE, W3SCHOOLS, Relation.CONTRADICT,
             "Different timing: devguide reflects the current state, w3schools is undated and stuck on an older version."),
        pair(REALPYTHON, W3SCHOOLS, Relation.CONTRADICT, "Different numbers: 3.13 and 3.11 cannot both be the latest release."),
    )
    judgment = Judgment(
        answer="The latest stable Python release is the 3.13 series, specifically 3.13.1.",
        confidence=0.86,
        reasoning="Two primary sources (the python.org downloads page and the official devguide) corroborate "
        "3.13 as the current stable branch, and the news source agrees. The 3.11 figure from w3schools carries "
        "no publication date and reflects a long-unmaintained page rather than a difference in definition, "
        "so it is not trusted.",
        conflicts=(
            "w3schools claims 3.11 is the latest, conflicting with the primary sources' 3.13; "
            "the cause is a stale page, not a difference in scope or definition.",
        ),
        trusted_sources=(DOWNLOADS.url, DEVGUIDE.url, REALPYTHON.url),
        usage=usage(3100, 420),
    )
    pages = tuple(page(source) for source in SOURCES)
    return run(question, datetime(2026, 9, 12, 20, 18, 18, tzinfo=UTC), pages, claims, pairs, judgment)


def all_agree_run() -> RunResult:
    base = base_run()
    w3schools = replace(
        base.claims[3],
        text="The latest stable Python release is 3.13.",
        evidence="Python 3.13 is the latest stable release",
        published_date="2025-10-14",
    )
    pairs = tuple(
        replace(p, relation=Relation.AGREE, nature="Both agree that 3.13 is the current latest stable release.")
        for p in base.pairs
    )
    judgment = replace(
        base.judgment,
        confidence=0.97,
        reasoning="All four sources point at 3.13; the two primary sources, the news article and the aggregator "
        "corroborate each other, so there is no disagreement to reconcile.",
        conflicts=(),
        trusted_sources=tuple(source.url for source in SOURCES),
    )
    question = replace(base.question, id="sample-all-agree")
    claims = (*base.claims[:3], w3schools)
    return run(question, datetime(2026, 9, 12, 21, 2, 0, tzinfo=UTC), base.pages, claims, pairs, judgment)


def failures_run() -> RunResult:
    """devguide 抓取失败（所以没有它的主张，也不参与比对），另有一次比对返回的不是合法 JSON。"""
    base = base_run()
    pages = tuple(
        Page(url=p.url, ok=False, error="Steel 429 Too Many Requests", fetched_at=FETCHED_AT) if p.url == DEVGUIDE.url else p
        for p in base.pages
    )
    claims = tuple(c for c in base.claims if c.source_url != DEVGUIDE.url)
    pairs = tuple(p for p in base.pairs if DEVGUIDE.url not in (p.a_url, p.b_url))
    broken = replace(
        pairs[1],
        relation=None,
        nature=None,
        failure=Failure(step="pair", detail="JSONDecodeError: Expecting value: line 1 column 1 (char 0)", raw=""),
    )
    pairs = (pairs[0], broken, *pairs[2:])
    judgment = replace(base.judgment, confidence=0.42, trusted_sources=(DOWNLOADS.url, REALPYTHON.url))
    question = replace(base.question, id="sample-with-failures")
    return run(question, datetime(2026, 9, 12, 21, 30, 0, tzinfo=UTC), pages, claims, pairs, judgment)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=RUNS_DIR, help="where to write the sample runs (default out/runs)")
    out = parser.parse_args().out
    out.mkdir(parents=True, exist_ok=True)
    for result in (base_run(), all_agree_run(), failures_run()):
        stamp = result.started_at.strftime("%Y%m%dT%H%M%SZ")
        path = out / f"{result.question.id}_{stamp}.json"
        path.write_text(json.dumps(run_record(result), ensure_ascii=False, indent=2), encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
