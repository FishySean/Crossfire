"""生成本地样例结果文件，供 web 界面开发与验收使用（不调用任何外部 API）。"""

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
        "markdown": f"# {title}\n\n(样例内容)",
        "links": [],
        "error": None,
        "status_code": 200,
    }


def base_run():
    claims = [
        claim(
            PY_SOURCES[0][0],
            "primary",
            "Python 当前的最新稳定版本是 3.13.1。",
            "Download the latest version for Windows — Python 3.13.1",
            "official_documentation",
            0.95,
            "2025-12-03",
        ),
        claim(
            PY_SOURCES[1][0],
            "primary",
            "3.13 是当前的 bugfix 分支，即最新稳定版本。",
            "3.13 bugfix security 2024-10-07 2029-10",
            "official_documentation",
            0.92,
            "2025-11-20",
        ),
        claim(
            PY_SOURCES[2][0],
            "news",
            "Python 3.13 已发布，是目前可用的最新版本。",
            "Python 3.13 is now available with a new REPL and free-threaded mode",
            "news_article",
            0.8,
            "2024-10-08",
        ),
        claim(
            PY_SOURCES[3][0],
            "aggregator",
            "最新的 Python 主版本是 3.11。",
            "The most recent major version of Python is Python 3",
            "encyclopedia",
            0.6,
            None,
        ),
    ]
    pairs = [
        pair(PY_SOURCES[0][0], PY_SOURCES[1][0], "agree", "两者一致认为 3.13 系列是当前稳定分支。"),
        pair(PY_SOURCES[0][0], PY_SOURCES[2][0], "agree", "都指向 3.13，只是精确到的小版本粒度不同。"),
        pair(
            PY_SOURCES[0][0],
            PY_SOURCES[3][0],
            "contradict",
            "数字不同：python.org 给出 3.13.1，w3schools 仍写 3.11，后者页面陈旧。",
        ),
        pair(PY_SOURCES[1][0], PY_SOURCES[2][0], "agree", "一致在 3.13 为当前 bugfix 分支这一点上。"),
        pair(
            PY_SOURCES[1][0],
            PY_SOURCES[3][0],
            "contradict",
            "时间不同：devguide 反映当前状态，w3schools 未标日期且停留在旧版本。",
        ),
        pair(
            PY_SOURCES[2][0],
            PY_SOURCES[3][0],
            "contradict",
            "数字不同：3.13 与 3.11 不能同时是最新版本。",
        ),
    ]
    judgment = {
        "answer": "Python 目前的最新稳定版本是 3.13 系列，具体到 3.13.1。",
        "confidence": 0.86,
        "reasoning": "两个一手源（python.org 下载页与官方 devguide）互相印证 3.13 为当前稳定分支，"
        "新闻源与之一致。w3schools 给出的 3.11 没有发布日期，属于页面长期未更新造成的陈旧信息，"
        "不构成口径差异，因此不予采信。",
        "conflicts": [
            "w3schools 声称最新为 3.11，与一手源的 3.13 冲突，性质是页面陈旧而非统计口径差异。",
        ],
        "trusted_sources": [PY_SOURCES[0][0], PY_SOURCES[1][0], PY_SOURCES[2][0]],
        "usage": {"input_tokens": 3100, "output_tokens": 420},
    }
    return {
        "question_id": "python-latest-version",
        "question": "Python 目前的最新稳定版本是哪一个？",
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
    run["claims"][3]["claim"] = "Python 当前的最新稳定版本是 3.13。"
    run["claims"][3]["evidence"] = "Python 3.13 is the latest stable release"
    run["claims"][3]["published_date"] = "2025-10-14"
    for p in run["pairs"]:
        p["relation"] = "agree"
        p["nature"] = "两者一致认为 3.13 是当前最新稳定版本。"
    run["judgment"]["confidence"] = 0.97
    run["judgment"]["reasoning"] = "四个来源全部指向 3.13，两个一手源与新闻、聚合站互相印证，没有需要调和的分歧。"
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
        {"stage": "pair", "url": None, "error": "Claude 响应不是合法 JSON，已跳过该配对"},
    ]
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
