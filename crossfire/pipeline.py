import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from crossfire.extract import extract_claim
from crossfire.reconcile import DEFAULT_PAIR_CONCURRENCY, judge, pair_claims
from crossfire.steel_client import CACHE_ROOT, fetch_pages

RUNS_DIR = Path(__file__).resolve().parents[1] / "out" / "runs"


def _step_usage(records: list[dict], seconds: float) -> dict:
    usages = [r["usage"] for r in records if r.get("usage")]
    return {
        "calls": len(usages),
        "input_tokens": sum(u["input_tokens"] for u in usages),
        "output_tokens": sum(u["output_tokens"] for u in usages),
        "seconds": seconds,
    }


def run(
    question_config: dict,
    on_event=None,
    mode: str = "live",
    pair_concurrency: int = DEFAULT_PAIR_CONCURRENCY,
) -> dict:
    emit = on_event if on_event else lambda event: None

    started = time.monotonic()
    started_at = datetime.now(timezone.utc)

    question = question_config["question"]
    sources = question_config["sources"]
    urls = [s["url"] for s in sources]
    tier_by_url = {s["url"]: s.get("tier") for s in sources}

    emit({"type": "start", "question": question, "total_sources": len(sources)})

    def on_page(index: int, page: dict) -> None:
        emit(
            {
                "type": "fetch_done",
                "url": page["url"],
                "ok": page["ok"],
                "chars": len(page.get("markdown") or ""),
                "index": index,
            }
        )
        if not page["ok"]:
            emit({"type": "error", "step": "fetch", "detail": page["error"]})

    fetch_started = time.monotonic()
    pages = asyncio.run(
        fetch_pages(
            urls,
            use_cache=(mode == "cached"),
            cache_dir=CACHE_ROOT / question_config["id"],
            on_page=on_page,
        )
    )
    fetch_seconds = round(time.monotonic() - fetch_started, 2)

    extract_started = time.monotonic()
    claims = []
    # index 必须是来源在 sources 里的下标，跟 fetch_done 对齐：前端按它往固定的卡片槽位里填。
    # 用 claims 的长度会在有页面抓取失败时整体错位，把主张画到别的来源上。
    for index, page in enumerate(pages):
        if not page["ok"]:
            continue
        claim = extract_claim(question, {**page, "tier": tier_by_url.get(page["url"])})
        claims.append(claim)
        emit(
            {
                "type": "claim_done",
                "url": claim["url"],
                "claim": claim["claim"],
                "tier": claim["tier"],
                "index": index,
            }
        )
        if claim.get("failure"):
            emit({"type": "error", "step": "extract", "detail": claim["failure"]["detail"]})
    extract_seconds = round(time.monotonic() - extract_started, 2)

    answered = sum(1 for c in claims if c.get("claim"))
    emit({"type": "pair_start", "total_pairs": answered * (answered - 1) // 2})

    def on_pair(index: int, total: int, pair: dict) -> None:
        emit(
            {
                "type": "pair_done",
                "a_url": pair["a"],
                "b_url": pair["b"],
                "relation": pair["relation"],
                "nature": pair["nature"],
                "index": index,
                "total": total,
            }
        )
        if pair.get("failure"):
            emit({"type": "error", "step": "pair", "detail": pair["failure"]["detail"]})

    pair_started = time.monotonic()
    pairs = asyncio.run(pair_claims(question, claims, concurrency=pair_concurrency, on_pair=on_pair))
    pair_seconds = round(time.monotonic() - pair_started, 2)

    emit({"type": "judge_start"})
    judge_started = time.monotonic()
    judgment = judge(question, claims, pairs)
    judge_seconds = round(time.monotonic() - judge_started, 2)
    if judgment.get("failure"):
        emit({"type": "error", "step": "judge", "detail": judgment["failure"]["detail"]})

    steps = {
        "fetch": {"calls": len(pages), "seconds": fetch_seconds},
        "extract": _step_usage(claims, extract_seconds),
        "pair": _step_usage(pairs, pair_seconds),
        "judge": _step_usage([judgment], judge_seconds),
    }
    failures = [r["failure"] for r in [*claims, *pairs, judgment] if r.get("failure")]

    result = {
        "question_id": question_config["id"],
        "question": question,
        "mode": mode,
        "started_at": started_at.isoformat(),
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "sources": sources,
        "pages_fetched": sum(1 for p in pages if p["ok"]),
        "pages_failed": sum(1 for p in pages if not p["ok"]),
        "claude_calls": len(claims) + len(pairs) + 1,
        "failures": failures,
        "steps": steps,
        "total_input_tokens": sum(s.get("input_tokens", 0) for s in steps.values()),
        "total_output_tokens": sum(s.get("output_tokens", 0) for s in steps.values()),
        "pages": pages,
        "claims": claims,
        "pairs": pairs,
        "judgment": judgment,
    }

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    path = RUNS_DIR / f"{question_config['id']}_{timestamp}.json"
    staging = path.with_suffix(".json.tmp")
    staging.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(staging, path)
    result["output_path"] = str(path)

    emit(
        {
            "type": "done",
            "judgment": judgment,
            "run_file": str(path),
            "elapsed": result["elapsed_seconds"],
        }
    )

    return result
