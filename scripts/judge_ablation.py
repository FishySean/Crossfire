"""判决 prompt 里「关于你自己的知识」那段有没有用：同一批冻结输入，有那段和删掉那段各判一遍。

只调判决，每份输入一次请求。默认用 judge-python-2026-11 的三份输入，共 6 次请求。
结果打一张对照表，完整的答案和推理存进 out/judge-ablation/<时间>.json。
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import crossfire.composition as composition
from crossfire.application.use_cases import CaseOutcome
from crossfire.config import ROOT, Key, Settings, load_eval_cases, load_judge_inputs, load_questions
from crossfire.domain.evals import CaseKind

VARIANTS = {"保留那段": False, "删掉那段": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default="judge-python-2026-11")
    parser.add_argument("--estimate-only", action="store_true")
    args = parser.parse_args()

    settings = Settings.from_env(require=[Key.ANTHROPIC])
    case = next((c for c in load_eval_cases(settings) if c.id == args.case), None)
    if case is None or case.kind is not CaseKind.JUDGE:
        parser.error(f"{args.case} 不是 judge 题")
    question = next(q for q in load_questions(settings) if q.id == case.question_id)
    inputs = load_judge_inputs(settings, case)

    total = len(inputs) * case.repeats * len(VARIANTS)
    print(f"预计请求数：{len(inputs)} 份输入 × {case.repeats} 次 × {len(VARIANTS)} 种 prompt = 最多 {total} 次（不含重试）")
    if args.estimate_only:
        return 0

    outcomes: dict[str, CaseOutcome] = {}
    for name, drop in VARIANTS.items():
        print(f"\n=== {name} ===")
        runner = composition.build_judge_eval_runner(settings, drop_sources_over_memory=drop)
        outcomes[name] = runner.execute(case, question, inputs)

    print(f"\n{'prompt':<8}{'输入':<22}{'结果':<6}{'置信度':>6}  答案 / 没通过的原因")
    report: dict[str, list[dict[str, object]]] = {}
    for name, outcome in outcomes.items():
        rows = report.setdefault(name, [])
        for attempt in outcome.attempts:
            judgment = attempt.judgment
            flag = "通过" if attempt.grade.passed else "没通过"
            confidence = "n/a" if judgment.confidence is None else f"{judgment.confidence:.2f}"
            source = (attempt.source or "").rsplit("_", 1)[-1]
            answer = " ".join((judgment.answer or "(没有答案)").split())
            print(f"{name:<8}{source:<22}{flag:<6}{confidence:>6}  {answer[:80]}")
            for reason in attempt.grade.reasons:
                print(f"{'':<44}✗ {reason[:100]}")
            rows.append(
                {
                    "source": attempt.source,
                    "passed": attempt.grade.passed,
                    "reasons": list(attempt.grade.reasons),
                    "judgment": judgment.to_dict(),
                }
            )
    for name, outcome in outcomes.items():
        passed = sum(attempt.grade.passed for attempt in outcome.attempts)
        print(f"{name}：{passed}/{len(outcome.attempts)} 次通过")

    attempts = [attempt for outcome in outcomes.values() for attempt in outcome.attempts]
    requests = sum(attempt.requests or 0 for attempt in attempts)
    tokens_in = sum(attempt.input_tokens for attempt in attempts)
    tokens_out = sum(attempt.output_tokens for attempt in attempts)
    print(f"实际请求 {requests} 次，token 输入 {tokens_in}，输出 {tokens_out}")

    out_dir = ROOT / "out" / "judge-ablation"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{case.id}_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(
        json.dumps({"case": case.id, "as_of": case.as_of.isoformat(), "variants": report}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"完整结果：{Path(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
