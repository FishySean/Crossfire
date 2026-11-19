import itertools
import json
import os
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from crossfire.application.ports import ClaimExtractor, ClaimPairer, PageFetcher, VerdictJudge
from crossfire.application.records import page_record
from crossfire.domain import Claim, Mode, Page, Pair, Question, SourceIndex

RUNS_DIR = Path(__file__).resolve().parents[1] / "out" / "runs"
HEARTBEAT_SECONDS = 5

type Event = dict[str, Any]


def _step_usage(records: list[dict[str, Any]], seconds: float) -> dict[str, Any]:
    usages = [r["usage"] for r in records if r.get("usage")]
    return {
        "calls": len(usages),
        "input_tokens": sum(u["input_tokens"] for u in usages),
        "output_tokens": sum(u["output_tokens"] for u in usages),
        "seconds": seconds,
    }


def run(
    question: Question,
    fetcher: PageFetcher,
    extractor: ClaimExtractor,
    pairer: ClaimPairer,
    judge: VerdictJudge,
    on_event: Callable[[Event], None] | None = None,
    mode: Mode = Mode.LIVE,
) -> dict[str, Any]:
    if not isinstance(mode, Mode):
        raise TypeError(f"mode 必须是 Mode，收到 {mode!r}；字符串请在入口处用 Mode(...) 转换")
    emit = on_event if on_event else lambda event: None

    started = time.monotonic()
    started_at = datetime.now(timezone.utc)

    sources = question.to_dict()["sources"]
    urls = [source.url for source in question.sources]

    emit({"type": "start", "question": question.text, "total_sources": len(question.sources)})

    def on_page(index: SourceIndex, page: Page) -> None:
        emit(
            {
                "type": "fetch_done",
                "url": page.url,
                "ok": page.ok,
                "chars": len(page.markdown or ""),
                "index": index,
            }
        )
        if not page.ok:
            emit({"type": "error", "step": "fetch", "detail": page.error})

    fetch_started = time.monotonic()
    pages = fetcher.fetch_all(urls, on_page)
    fetch_seconds = round(time.monotonic() - fetch_started, 2)

    extract_started = time.monotonic()
    claims: list[Claim] = []
    # index 必须是来源在 sources 里的下标，跟 fetch_done 对齐：前端按它往固定的卡片槽位里填。
    # 用 claims 的长度会在有页面抓取失败时整体错位，把主张画到别的来源上。
    for page in pages:
        if not page.ok:
            continue
        index = question.index_of(page.url)
        claim = extractor.extract(question, page)
        claims.append(claim)
        emit(
            {
                "type": "claim_done",
                "url": claim.source_url,
                "claim": claim.text,
                "tier": claim.tier.value,
                "index": index,
            }
        )
        if claim.failure:
            emit({"type": "error", "step": "extract", "detail": claim.failure.detail})
    extract_seconds = round(time.monotonic() - extract_started, 2)

    claim_pairs = list(itertools.combinations([c for c in claims if c.answered], 2))
    emit({"type": "pair_start", "total_pairs": len(claim_pairs)})

    def on_pair(index: int, total: int, pair: Pair) -> None:
        emit(
            {
                "type": "pair_done",
                "a_url": pair.a_url,
                "b_url": pair.b_url,
                "relation": None if pair.relation is None else pair.relation.value,
                "nature": pair.nature,
                "index": index,
                "total": total,
            }
        )
        if pair.failure:
            emit({"type": "error", "step": "pair", "detail": pair.failure.detail})

    pair_started = time.monotonic()
    pairs = pairer.pair_all(question, claim_pairs, on_pair)
    pair_seconds = round(time.monotonic() - pair_started, 2)

    emit({"type": "judge_start"})
    judge_started = time.monotonic()

    # judge 是一次阻塞调用，中间没有任何可报告的进度，实测能跑到 27 秒。
    # 心跳只说明「还在跑、跑了多久」，不编造进度，让前端的超时计时器有东西可重置。
    stop_beating = threading.Event()

    def beat() -> None:
        while not stop_beating.wait(HEARTBEAT_SECONDS):
            emit(
                {
                    "type": "heartbeat",
                    "step": "judge",
                    "elapsed": round(time.monotonic() - judge_started, 2),
                }
            )

    heartbeat = threading.Thread(target=beat, daemon=True) if on_event else None
    if heartbeat:
        heartbeat.start()
    try:
        verdict = judge.judge(question, claims, pairs)
    finally:
        stop_beating.set()
        if heartbeat:
            heartbeat.join()
    judge_seconds = round(time.monotonic() - judge_started, 2)
    if verdict.failure:
        emit({"type": "error", "step": "judge", "detail": verdict.failure.detail})

    page_records = [page_record(page) for page in pages]
    claim_records = [claim.to_dict() for claim in claims]
    pair_records = [pair.to_dict() for pair in pairs]
    judgment = verdict.to_dict()

    steps = {
        "fetch": {"calls": len(pages), "seconds": fetch_seconds},
        "extract": _step_usage(claim_records, extract_seconds),
        "pair": _step_usage(pair_records, pair_seconds),
        "judge": _step_usage([judgment], judge_seconds),
    }
    failures = [r["failure"] for r in [*claim_records, *pair_records, judgment] if r.get("failure")]

    result: dict[str, Any] = {
        "question_id": question.id,
        "question": question.text,
        "mode": mode.value,
        "started_at": started_at.isoformat(),
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "sources": sources,
        "pages_fetched": sum(1 for p in pages if p.ok),
        "pages_failed": sum(1 for p in pages if not p.ok),
        "claude_calls": len(claims) + len(pairs) + 1,
        "failures": failures,
        "steps": steps,
        "total_input_tokens": sum(s.get("input_tokens", 0) for s in steps.values()),
        "total_output_tokens": sum(s.get("output_tokens", 0) for s in steps.values()),
        "pages": page_records,
        "claims": claim_records,
        "pairs": pair_records,
        "judgment": judgment,
    }

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    path = RUNS_DIR / f"{question.id}_{timestamp}.json"
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
