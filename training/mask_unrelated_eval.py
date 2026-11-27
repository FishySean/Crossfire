"""第 10b：在 Drive 上的 v1/v2 多种子 checkpoint 上对比屏蔽 unrelated 开/关。

供 Colab §10 调用：发现目录 → 逐种子 --compare-mask → 汇总均值±标准差 → 写 JSON。
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from training.evaluate import compare_mask_checkpoint
from training.labels import LABELS

DEFAULT_RUNS_ROOT = Path("/content/drive/MyDrive/crossfire-runs")
V1_RUN_NAME = "run-20261121-235427"
SEEDS = (42, 43, 44)


@dataclass(frozen=True)
class RunLayout:
    name: str
    root: Path
    seed_dirs: dict[int, Path]


def _has_checkpoint(seed_dir: Path) -> bool:
    ckpt = seed_dir / "best_checkpoint"
    if not ckpt.is_dir():
        return False
    return (ckpt / "config.json").is_file() and (
        (ckpt / "model.safetensors").is_file() or (ckpt / "pytorch_model.bin").is_file()
    )


def list_runs(runs_root: Path) -> list[str]:
    if not runs_root.is_dir():
        return []
    return sorted(p.name for p in runs_root.iterdir() if p.is_dir())


def resolve_v1(runs_root: Path, run_name: str = V1_RUN_NAME) -> RunLayout:
    root = runs_root / run_name
    if not root.is_dir():
        found = list_runs(runs_root)
        raise FileNotFoundError(
            f"找不到 v1 目录：{root}\n"
            f"crossfire-runs/ 下实际有：{found if found else '(空或不存在)'}"
        )
    seed_dirs: dict[int, Path] = {}
    missing: list[str] = []
    for seed in SEEDS:
        seed_dir = root / "seeds" / f"seed_{seed}"
        if _has_checkpoint(seed_dir):
            seed_dirs[seed] = seed_dir / "best_checkpoint"
        else:
            missing.append(str(seed_dir / "best_checkpoint"))
    if missing:
        raise FileNotFoundError(
            f"v1 {run_name} 缺少完整 best_checkpoint：\n- "
            + "\n- ".join(missing)
            + f"\ncrossfire-runs/ 下实际有：{list_runs(runs_root)}"
        )
    return RunLayout(name=run_name, root=root, seed_dirs=seed_dirs)


def resolve_latest_complete_iter2_final(runs_root: Path) -> RunLayout:
    """取最新的、三种子 best_checkpoint 齐全的 iter2-final-*。"""
    candidates = sorted(
        (p for p in runs_root.glob("iter2-final-*") if p.is_dir()),
        key=lambda p: p.name,
    )
    if not candidates:
        raise FileNotFoundError(
            "找不到任何 iter2-final-* 目录。\n"
            f"crossfire-runs/ 下实际有：{list_runs(runs_root)}"
        )
    incomplete: list[str] = []
    for root in reversed(candidates):  # 名字含时间戳，倒序 ≈ 最新优先
        seed_dirs: dict[int, Path] = {}
        missing: list[str] = []
        for seed in SEEDS:
            seed_dir = root / "seeds" / f"seed_{seed}"
            if _has_checkpoint(seed_dir):
                seed_dirs[seed] = seed_dir / "best_checkpoint"
            else:
                missing.append(str(seed_dir / "best_checkpoint"))
        if not missing:
            return RunLayout(name=root.name, root=root, seed_dirs=seed_dirs)
        incomplete.append(f"{root.name} 缺：{', '.join(missing)}")
    raise FileNotFoundError(
        "有 iter2-final-* 但没有「三种子 best_checkpoint 齐全」的完整目录：\n- "
        + "\n- ".join(incomplete)
        + f"\ncrossfire-runs/ 下实际有：{list_runs(runs_root)}"
    )


def _mean_std(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": float("nan"), "std": float("nan")}
    mean = statistics.fmean(values)
    std = statistics.pstdev(values) if len(values) > 1 else 0.0
    return {"mean": mean, "std": std}


def _per_class_mean_std(seed_reports: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for label in LABELS:
        f1s = [float(r["report"]["per_class"][label]["f1"]) for r in seed_reports]
        out[label] = _mean_std(f1s)
    return out


def evaluate_run(
    layout: RunLayout,
    *,
    pairs_path: Path,
    split: str = "test",
    version_tag: str,
) -> dict[str, Any]:
    seeds_out: list[dict[str, Any]] = []
    for seed, ckpt in sorted(layout.seed_dirs.items()):
        print(f"\n===== {version_tag} seed={seed}  {ckpt} =====", flush=True)
        cmp = compare_mask_checkpoint(ckpt, pairs_path, split=split)
        seeds_out.append(
            {
                "seed": seed,
                "checkpoint": str(ckpt),
                "off_macro_f1": cmp["off"]["report"]["macro_f1"],
                "on_macro_f1": cmp["on"]["report"]["macro_f1"],
                "off_accuracy": cmp["off"]["report"]["accuracy"],
                "on_accuracy": cmp["on"]["report"]["accuracy"],
                "correct_to_wrong": cmp["flips"]["correct_to_wrong"],
                "wrong_to_correct": cmp["flips"]["wrong_to_correct"],
                "wrong_to_wrong_changed": cmp["flips"]["wrong_to_wrong_changed"],
                "gate_ok": cmp["gate_correct_to_wrong_zero"],
                "compare": cmp,
            }
        )
        print(
            f"  off macro={cmp['off']['report']['macro_f1']:.4f}  "
            f"on macro={cmp['on']['report']['macro_f1']:.4f}  "
            f"correct→wrong={cmp['flips']['correct_to_wrong']}  "
            f"wrong→correct={cmp['flips']['wrong_to_correct']}",
            flush=True,
        )

    def _side(side: str) -> dict[str, Any]:
        key_f1 = f"{side}_macro_f1"
        key_acc = f"{side}_accuracy"
        reports = [
            s["compare"][side]
            for s in seeds_out
        ]
        return {
            "macro_f1": _mean_std([float(s[key_f1]) for s in seeds_out]),
            "accuracy": _mean_std([float(s[key_acc]) for s in seeds_out]),
            "per_class_f1": _per_class_mean_std(reports),
            "unrelated_predictions_mean": statistics.fmean(
                float(s["compare"][side]["unrelated_predictions"]) for s in seeds_out
            ),
        }

    summary = {
        "version": version_tag,
        "run": layout.name,
        "run_root": str(layout.root),
        "n_seeds": len(seeds_out),
        "correct_to_wrong_total": sum(s["correct_to_wrong"] for s in seeds_out),
        "wrong_to_correct_total": sum(s["wrong_to_correct"] for s in seeds_out),
        "any_correct_to_wrong": any(s["correct_to_wrong"] for s in seeds_out),
        "off": _side("off"),
        "on": _side("on"),
        "seeds": seeds_out,
    }
    return summary


def _fmt_ms(ms: dict[str, float]) -> str:
    mean, std = ms["mean"], ms["std"]
    if math.isnan(mean):
        return "n/a"
    return f"{mean:.4f} ± {std:.4f}"


def print_summary_table(summaries: list[dict[str, Any]]) -> None:
    print("\n" + "=" * 72)
    print("屏蔽 unrelated：测试集汇总")
    print("=" * 72)
    header = (
        f"{'version':8s} {'mask':4s} {'macro-F1':16s} {'accuracy':16s} "
        f"{'agree':10s} {'contradict':10s} {'scope':10s} "
        f"{'c→w':5s} {'w→c':5s}"
    )
    print(header)
    for summary in summaries:
        for side in ("off", "on"):
            block = summary[side]
            pc = block["per_class_f1"]
            flips_c2w = summary["correct_to_wrong_total"] if side == "on" else "—"
            flips_w2c = summary["wrong_to_correct_total"] if side == "on" else "—"
            # 翻转相对「关→开」；只在 on 行显示累计
            print(
                f"{summary['version']:8s} {side:4s} "
                f"{_fmt_ms(block['macro_f1']):16s} "
                f"{_fmt_ms(block['accuracy']):16s} "
                f"{_fmt_ms(pc['agree']):10s} "
                f"{_fmt_ms(pc['contradict']):10s} "
                f"{_fmt_ms(pc['same_question_different_scope']):10s} "
                f"{str(flips_c2w):5s} {str(flips_w2c):5s}"
            )
        print(
            f"  run={summary['run']}  "
            f"any_correct→wrong={summary['any_correct_to_wrong']}"
        )
    print("=" * 72)


def run_colab_eval(
    *,
    runs_root: Path | str = DEFAULT_RUNS_ROOT,
    pairs_path: Path | str = "data/pairs.jsonl",
    out_dir: Path | str | None = None,
    v1_run_name: str = V1_RUN_NAME,
) -> dict[str, Any]:
    runs_root = Path(runs_root)
    pairs_path = Path(pairs_path)
    if out_dir is None:
        out_dir = runs_root / "iter2-mask-eval"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"runs_root = {runs_root}", flush=True)
    print(f"pairs     = {pairs_path}", flush=True)
    print(f"out_dir   = {out_dir}", flush=True)
    print(f"crossfire-runs/ 目录列表：{list_runs(runs_root)}", flush=True)

    v1 = resolve_v1(runs_root, v1_run_name)
    v2 = resolve_latest_complete_iter2_final(runs_root)
    print(f"选用 v1: {v1.root}", flush=True)
    print(f"选用 v2: {v2.root}", flush=True)

    summaries = [
        evaluate_run(v1, pairs_path=pairs_path, version_tag="v1"),
        evaluate_run(v2, pairs_path=pairs_path, version_tag="v2"),
    ]
    print_summary_table(summaries)

    payload = {
        "pairs_path": str(pairs_path),
        "runs_root": str(runs_root),
        "v1_run": v1.name,
        "v2_run": v2.name,
        "summaries": summaries,
        "publish_gate_ok": not any(s["any_correct_to_wrong"] for s in summaries),
    }
    out_path = out_dir / "mask-unrelated-test-compare.json"
    # seeds 里嵌了完整 compare，体积大但方便复查；另存精简版
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    slim = {
        **{k: payload[k] for k in ("pairs_path", "runs_root", "v1_run", "v2_run", "publish_gate_ok")},
        "summaries": [
            {
                "version": s["version"],
                "run": s["run"],
                "correct_to_wrong_total": s["correct_to_wrong_total"],
                "wrong_to_correct_total": s["wrong_to_correct_total"],
                "any_correct_to_wrong": s["any_correct_to_wrong"],
                "off": s["off"],
                "on": s["on"],
                "seeds": [
                    {
                        "seed": x["seed"],
                        "off_macro_f1": x["off_macro_f1"],
                        "on_macro_f1": x["on_macro_f1"],
                        "off_accuracy": x["off_accuracy"],
                        "on_accuracy": x["on_accuracy"],
                        "correct_to_wrong": x["correct_to_wrong"],
                        "wrong_to_correct": x["wrong_to_correct"],
                        "gate_ok": x["gate_ok"],
                    }
                    for x in s["seeds"]
                ],
            }
            for s in summaries
        ],
    }
    slim_path = out_dir / "mask-unrelated-test-compare.slim.json"
    slim_path.write_text(json.dumps(slim, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n已写入：{out_path}", flush=True)
    print(f"精简版：{slim_path}", flush=True)
    if not payload["publish_gate_ok"]:
        print(
            "\n*** 闸门失败：存在正确→错误；不要发布。***",
            flush=True,
        )
    else:
        print("\n闸门通过：所有评测种子上正确→错误均为 0。", flush=True)
    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Colab/Drive：v1+v2 三种子屏蔽 unrelated 开/关评估")
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--pairs", type=Path, default=Path("data/pairs.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--v1-run", default=V1_RUN_NAME)
    args = parser.parse_args(argv)
    run_colab_eval(
        runs_root=args.runs_root,
        pairs_path=args.pairs,
        out_dir=args.out_dir,
        v1_run_name=args.v1_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
