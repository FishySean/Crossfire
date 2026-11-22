#!/usr/bin/env python3
"""把本地 models/crossfire-pairer-v1 上传到 Hugging Face（默认私有）。

不会在代码或日志里出现 token。请你自己先登录：

  1. 打开 https://huggingface.co/settings/tokens
  2. Create new token，类型选 Write，名字例如 crossfire-upload
  3. 在本机终端执行（把令牌粘贴在提示处，不要发给任何人）：

       uv run --group train hf auth login

  4. 再运行本脚本。上传成功后把打印的 commit hash 填进
     crossfire/config.py 的 DEFAULT_NLI_MODEL_REVISION。

默认 --private。你在网页上确认 model card 无误后，再在 HF 设置里改成公开。
本脚本默认不替你改公开。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from crossfire.config import ROOT

DEFAULT_REPO = "FishySean/crossfire-pairer"
DEFAULT_LOCAL = ROOT / "models" / "crossfire-pairer-v1"

# 只上传推理与说明需要的文件；不要把优化器状态或训练中间产物传上去。
ALLOW = {
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "README.md",
    "test_report.json",
    "test_report.md",
    "summary.json",
    "pack_meta.json",
    "run_meta.json",
    "fp16_vs_fp32.json",
}

FORBIDDEN_SUBSTRINGS = ("optimizer", "scheduler", "rng_state", "train_state", ".pt", ".pth")


def _check_local(package: Path) -> None:
    if not package.is_dir():
        raise SystemExit(f"找不到本地模型目录：{package}")
    card = package / "README.md"
    if not card.is_file():
        raise SystemExit(f"缺少 model card：{card}")
    weights = package / "model.safetensors"
    if not weights.is_file():
        raise SystemExit(f"缺少权重：{weights}")
    for path in package.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.lower()
        if any(bad in name for bad in FORBIDDEN_SUBSTRINGS):
            raise SystemExit(f"拒绝上传：疑似训练状态文件 {path.relative_to(package)}")
    meta = package / "pack_meta.json"
    if meta.is_file():
        data = json.loads(meta.read_text(encoding="utf-8"))
        if data.get("contains_optimizer_state"):
            raise SystemExit("pack_meta.json 标明含优化器状态，拒绝上传")


def _recheck_macro_f1(package: Path) -> float:
    """用仓库里的测试切分对 package 再评一次宏平均 F1。"""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    from training.evaluate import predict_labels
    from training.metrics import macro_f1
    from training.prepare import prepare_from_pairs

    prepared = prepare_from_pairs(ROOT / "data" / "pairs.jsonl")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    dtype = torch.float16 if device.type != "cpu" else torch.float32
    tokenizer = AutoTokenizer.from_pretrained(package, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        package, local_files_only=True, torch_dtype=dtype
    )
    model.to(device)
    model.eval()
    preds = predict_labels(model, list(prepared.test_rows), tokenizer, max_length=160)
    truths = [str(row["label"]) for row in prepared.test_rows]
    return float(macro_f1(truths, preds))


def _check_test_report(package: Path, re_eval: bool) -> None:
    report_path = package / "test_report.json"
    if not report_path.is_file():
        raise SystemExit("缺少 test_report.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if "test_macro_f1" in report:
        expected = float(report["test_macro_f1"])
    else:
        expected = float(report["model"]["macro_f1"])
    print(f"本地报告宏平均 F1 = {expected:.6f}")
    if not re_eval:
        print("跳过重新评估（默认）。上传前建议加 --re-eval（需 uv sync --group train 与 data/pairs.jsonl）。")
        return
    got = _recheck_macro_f1(package)
    if abs(got - expected) > 1e-4:
        raise SystemExit(f"重新评估 F1={got:.6f} 与报告 {expected:.6f} 不一致，中止上传")
    print(f"重新评估一致：{got:.6f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--package", type=Path, default=DEFAULT_LOCAL)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--private", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--re-eval", action="store_true", help="上传前用测试集重评（较慢）")
    parser.add_argument("--dry-run", action="store_true", help="只检查，不上传")
    args = parser.parse_args()

    package = args.package if args.package.is_absolute() else ROOT / args.package
    _check_local(package)
    _check_test_report(package, args.re_eval)

    files = [p for p in package.iterdir() if p.is_file() and p.name in ALLOW]
    missing = ALLOW - {p.name for p in files}
    for required in ("README.md", "model.safetensors", "config.json", "tokenizer.json"):
        if required in missing:
            raise SystemExit(f"缺少必需文件：{required}")
    print("将上传：")
    for path in sorted(files, key=lambda p: p.name):
        print(f"  {path.name}\t{path.stat().st_size / 1e6:.1f} MB")

    if args.dry_run:
        print("dry-run：检查通过，未上传。")
        return 0

    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("需要 huggingface_hub：uv sync --group train", file=sys.stderr)
        return 2

    api = HfApi()
    try:
        me = api.whoami()
    except Exception as error:
        print(
            f"尚未登录 Hugging Face（{type(error).__name__}: {error}）。\n"
            "请先在终端执行：uv run --group train hf auth login\n"
            "Token：https://huggingface.co/settings/tokens （选 Write）",
            file=sys.stderr,
        )
        return 2

    print(f"已登录为：{me.get('name') or me.get('fullname') or me}")
    api.create_repo(repo_id=args.repo, repo_type="model", private=args.private, exist_ok=True)
    commit = api.upload_folder(
        folder_path=str(package),
        repo_id=args.repo,
        repo_type="model",
        allow_patterns=sorted(ALLOW),
        commit_message="Add crossfire-pairer-v1 inference package",
    )
    rev = getattr(commit, "oid", None) or getattr(commit, "commit_hash", None) or str(commit)
    url = f"https://huggingface.co/{args.repo}"
    print()
    print(f"上传完成：{url}")
    print(f"本次 commit / revision：{rev}")
    print()
    print("请把下面这一行写进 crossfire/config.py 的 DEFAULT_NLI_MODEL_REVISION：")
    print(f'  DEFAULT_NLI_MODEL_REVISION = "{rev}"')
    print("确认 model card 无误后，在网页上把仓库从 Private 改成 Public。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
