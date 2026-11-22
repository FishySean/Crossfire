#!/usr/bin/env python3
"""免费对比：历史 Claude 比对结果 vs 本地 NLI（不重新调 Claude）。

默认读 out/runs 里最近一次有 28 对的 python-latest-stable 结果：
复用其中的主张，只跑 NLI，报告一致率、混淆最多的类别、以及本机耗时。
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from crossfire.composition import build_pairer
from crossfire.config import ROOT, Settings
from crossfire.domain import Claim, Pair, RunResult


def _latest_run(runs_dir: Path, question_id: str) -> Path:
    matches = sorted(runs_dir.glob(f"{question_id}_*.json"))
    if not matches:
        raise SystemExit(f"找不到 {question_id} 的历史结果：{runs_dir}")
    return matches[-1]


def _answered_claims(result: RunResult) -> list[Claim]:
    return [claim for claim in result.claims if claim.answered and claim.text]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        type=Path,
        default=None,
        help="历史结果 JSON（默认：out/runs 里最新的 python-latest-stable）",
    )
    parser.add_argument(
        "--model",
        default=str(ROOT / "models" / "crossfire-pairer-v1"),
        help="本地 NLI 模型目录",
    )
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()

    run_path = args.run or _latest_run(ROOT / "out" / "runs", "python-latest-stable")
    result = RunResult.from_dict(json.loads(run_path.read_text(encoding="utf-8")))
    claims = _answered_claims(result)
    claude_pairs = [p for p in result.pairs if p.relation is not None]
    if len(claude_pairs) < 2:
        raise SystemExit(f"{run_path} 里可用的 Claude 比对太少")

    by_url = {c.source_url: c for c in claims}
    claim_pairs: list[tuple[Claim, Claim]] = []
    ordered_claude: list[Pair] = []
    for pair in claude_pairs:
        a, b = by_url.get(pair.a_url), by_url.get(pair.b_url)
        if a is None or b is None:
            continue
        claim_pairs.append((a, b))
        ordered_claude.append(pair)

    n = len(claim_pairs)
    print(f"历史结果：{run_path.relative_to(ROOT)}")
    print(f"主张 {len(claims)} 条 → 比对 {n} 对（Claude pair 步 {result.steps.get('pair')}）")
    claude_seconds = None if "pair" not in result.steps else result.steps["pair"].seconds
    if claude_seconds is not None:
        print(f"Claude 比对当时耗时：{claude_seconds:.2f}s（约 {1000 * claude_seconds / n:.0f} ms/对）")

    model_path = Path(args.model)
    if not model_path.is_dir():
        raise SystemExit(f"模型目录不存在：{model_path}")

    settings = Settings.from_mapping(
        {
            "PAIRER": "nli",
            "NLI_MODEL": str(model_path),
            "NLI_BATCH_SIZE": str(args.batch_size),
            "ANTHROPIC_API_KEY": "unused-for-nli-only",
        }
    )
    pairer = build_pairer(settings)
    as_of = result.as_of or date.today()
    # 先触发加载，计时只含推理（不含首次读盘 ~550MB）
    _ = pairer.provenance
    t0 = time.perf_counter()
    nli_pairs = pairer.pair_all(result.question, claim_pairs, as_of)
    elapsed = time.perf_counter() - t0

    failed = sum(1 for p in nli_pairs if p.failure is not None)
    if failed:
        print(f"⚠️ NLI 失败 {failed}/{n} 对")

    agree = 0
    confusion: Counter[tuple[str, str]] = Counter()
    for claude, nli in zip(ordered_claude, nli_pairs, strict=True):
        if nli.relation is None or claude.relation is None:
            continue
        c_label, n_label = claude.relation.value, nli.relation.value
        if c_label == n_label:
            agree += 1
        else:
            confusion[(c_label, n_label)] += 1

    comparable = n - failed
    rate = agree / comparable if comparable else 0.0
    print()
    print(f"NLI 耗时：{elapsed:.2f}s，平均 {1000 * elapsed / n:.1f} ms/对（n={n}）")
    if claude_seconds and elapsed:
        print(f"相对 Claude：约 {claude_seconds / elapsed:.1f}× 更快")
    print(f"与 Claude 一致：{agree}/{comparable} = {rate:.1%}")
    if confusion:
        print("不一致最多（Claude → NLI）：")
        for (src, dst), count in confusion.most_common(8):
            print(f"  {src} → {dst}: {count}")

    out = ROOT / "out" / "pairer-compare" / f"compare_{datetime.now().strftime('%Y%m%dT%H%M%SZ')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "run": str(run_path),
                "model": str(model_path),
                "n_pairs": n,
                "agreement": rate,
                "agree_count": agree,
                "comparable": comparable,
                "nli_seconds": elapsed,
                "nli_ms_per_pair": 1000 * elapsed / n,
                "claude_pair_seconds": claude_seconds,
                "confusion": [{"claude": a, "nli": b, "count": c} for (a, b), c in confusion.most_common()],
                "provenance": pairer.provenance.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"明细写到 {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
