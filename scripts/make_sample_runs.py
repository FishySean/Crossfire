"""Generate local sample result files for developing and checking the viewer (no external API calls)."""

import json
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parents[1] / "out" / "runs"

PY_SOURCES = [
    ("https://www.python.org/downloads/", "primary"),
    ("https://devguide.python.org/versions/", "primary"),
    ("https://realpython.com/python313-new-features/", "news"),
    ("https://www.w3schools.com/python/python_intro.asp", "aggregator"),
]


def claim(url, tier, text, evidence, source_type, confidence, date):
    return {
        "url": url,
        "tier": tier,
        "claim": text,
        "evidence": evidence,
        "source_type": source_type,
        "confidence": confidence,
        "published_date": date,
        "usage": {"input_tokens": 4200, "output_tokens": 180},
    }


def page(url, title):
    return {
        "url": url,
        "ok": True,
        "title": title,
        "markdown": f"# {title}\n\n(sample content)",
        "links": [],
        "error": None,
        "status_code": 200,
    }


def base_run():
    claims = [
        claim(
            PY_SOURCES[0][0],
            "primary",
            "The latest stable Python release is 3.13.1.",
            "Download the latest version for Windows — Python 3.13.1",
            "official_documentation",
            0.95,
            "2025-12-03",
        ),
        claim(
            PY_SOURCES[1][0],
            "primary",
            "3.13 is the current bugfix branch, i.e. the latest stable release.",
            "3.13 bugfix security 2024-10-07 2029-10",
            "official_documentation",
            0.92,
            "2025-11-20",
        ),
        claim(
            PY_SOURCES[2][0],
            "news",
            "Python 3.13 has shipped and is the newest available release.",
            "Python 3.13 is now available with a new REPL and free-threaded mode",
            "news_article",
            0.8,
            "2024-10-08",
        ),
        claim(
            PY_SOURCES[3][0],
            "aggregator",
            "The most recent major Python version is 3.11.",
            "The most recent major version of Python is Python 3",
            "encyclopedia",
            0.6,
            None,
        ),
    ]
    pairs = [
        pair(PY_SOURCES[0][0], PY_SOURCES[1][0], "agree", "Both treat the 3.13 series as the current stable branch."),
        pair(PY_SOURCES[0][0], PY_SOURCES[2][0], "agree", "Both point at 3.13; only the patch-level granularity differs."),
        pair(
            PY_SOURCES[0][0],
            PY_SOURCES[3][0],
            "contradict",
            "Different numbers: python.org says 3.13.1 while w3schools still says 3.11 (stale page).",
        ),
        pair(PY_SOURCES[1][0], PY_SOURCES[2][0], "agree", "Both agree 3.13 is the current bugfix branch."),
        pair(
            PY_SOURCES[1][0],
            PY_SOURCES[3][0],
            "contradict",
            "Different timing: devguide reflects the current state, w3schools is undated and stuck on an older version.",
        ),
        pair(
            PY_SOURCES[2][0],
            PY_SOURCES[3][0],
            "contradict",
            "Different numbers: 3.13 and 3.11 cannot both be the latest release.",
        ),
    ]
    judgment = {
        "answer": "The latest stable Python release is the 3.13 series, specifically 3.13.1.",
        "confidence": 0.86,
        "reasoning": "Two primary sources (the python.org downloads page and the official devguide) corroborate "
        "3.13 as the current stable branch, and the news source agrees. The 3.11 figure from w3schools carries "
        "no publication date and reflects a long-unmaintained page rather than a difference in definition, "
        "so it is not trusted.",
        "conflicts": [
            "w3schools claims 3.11 is the latest, conflicting with the primary sources' 3.13; "
            "the cause is a stale page, not a difference in scope or definition.",
        ],
        "trusted_sources": [PY_SOURCES[0][0], PY_SOURCES[1][0], PY_SOURCES[2][0]],
        "usage": {"input_tokens": 3100, "output_tokens": 420},
    }
    return {
        "question_id": "python-latest-version",
        "question": "Which Python version is currently the latest stable release?",
        "started_at": "2026-09-12T20:18:18+00:00",
        "elapsed_seconds": 41.7,
        "sources": [{"url": url, "tier": tier} for url, tier in PY_SOURCES],
        "pages_fetched": 4,
        "pages_failed": 0,
        "claude_calls": 11,
        "steps": {},
        "total_input_tokens": 31200,
        "total_output_tokens": 2100,
        "pages": [page(url, url) for url, _ in PY_SOURCES],
        "claims": claims,
        "pairs": pairs,
        "judgment": judgment,
    }


def pair(a, b, relation, nature):
    return {
        "a": a,
        "b": b,
        "relation": relation,
        "nature": nature,
        "usage": {"input_tokens": 900, "output_tokens": 90},
    }


def all_agree_run():
    run = base_run()
    run["question_id"] = "sample-all-agree"
    run["started_at"] = "2026-09-12T21:02:00+00:00"
    run["claims"][3]["claim"] = "The latest stable Python release is 3.13."
    run["claims"][3]["evidence"] = "Python 3.13 is the latest stable release"
    run["claims"][3]["published_date"] = "2025-10-14"
    for p in run["pairs"]:
        p["relation"] = "agree"
        p["nature"] = "Both agree that 3.13 is the current latest stable release."
    run["judgment"]["confidence"] = 0.97
    run["judgment"]["reasoning"] = (
        "All four sources point at 3.13; the two primary sources, the news article and the aggregator "
        "corroborate each other, so there is no disagreement to reconcile."
    )
    run["judgment"]["conflicts"] = []
    run["judgment"]["trusted_sources"] = [url for url, _ in PY_SOURCES]
    return run


def failures_run():
    run = base_run()
    run["question_id"] = "sample-with-failures"
    run["started_at"] = "2026-09-12T21:30:00+00:00"
    run["pages_failed"] = 1
    run["judgment"]["confidence"] = 0.42
    run["failures"] = [
        {"stage": "fetch", "url": "https://devguide.python.org/versions/", "error": "Steel 429 Too Many Requests"},
    ]
    run["pairs"][1]["relation"] = None
    run["pairs"][1]["nature"] = None
    run["pairs"][1]["parse_error"] = "Expecting value: line 1 column 1 (char 0)"
    return run


def main():
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    files = {
        "python-latest-version_20260912T201818Z.json": base_run(),
        "sample-all-agree_20260912T210200Z.json": all_agree_run(),
        "sample-with-failures_20260912T213000Z.json": failures_run(),
    }
    for name, data in files.items():
        path = RUNS_DIR / name
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
