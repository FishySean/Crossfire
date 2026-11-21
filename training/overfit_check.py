"""第 8 步：拿 8 条训练样例反复训练，看损失能不能降到接近 0。

意义：如果连 8 条都背不下来，代码或精度有 bug，不必花钱租显卡。
默认用 CPU、纯 fp32。完整训练参数见第 9 步 README。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from transformers import AutoTokenizer

from training.amp import choose_amp, make_grad_scaler
from training.loop import assert_ready_to_train, batch_encode, class_weight_tensor, train_step
from training.prepare import prepare_from_pairs
from training.resize_head import BASE_MODEL_ID, load_four_way_model

# 过拟合检查是「能不能背下来」，不是正式训练：
# lr 略大、关掉 weight decay、不用类别权重（权重会把稀有类损失抬住，不容易贴到 0）。
DEFAULT_STEPS = 60
DEFAULT_LR = 2e-4
DEFAULT_N_EXAMPLES = 8
DEFAULT_MAX_LENGTH = 160
LOSS_OK_BELOW = 0.05


def pick_eight_examples(train_rows: list[dict], n: int = DEFAULT_N_EXAMPLES) -> list[dict]:
    """尽量四类都沾一点；不够就按顺序补齐。"""
    by_label: dict[str, list[dict]] = {}
    for row in train_rows:
        by_label.setdefault(str(row["label"]), []).append(row)
    picked: list[dict] = []
    # 每类先拿 2 条（四类 × 2 = 8）
    for label in ("agree", "contradict", "same_question_different_scope", "unrelated"):
        for row in by_label.get(label, [])[:2]:
            if len(picked) >= n:
                break
            picked.append(row)
    if len(picked) < n:
        for row in train_rows:
            if row in picked:
                continue
            picked.append(row)
            if len(picked) >= n:
                break
    if len(picked) < n:
        raise RuntimeError(f"训练集不够 {n} 条，只有 {len(picked)}")
    return picked[:n]


def run_overfit(
    *,
    pairs_path: Path,
    steps: int = DEFAULT_STEPS,
    lr: float = DEFAULT_LR,
    n_examples: int = DEFAULT_N_EXAMPLES,
    max_length: int = DEFAULT_MAX_LENGTH,
    model_id: str = BASE_MODEL_ID,
) -> dict:
    prepared = prepare_from_pairs(pairs_path)
    examples = pick_eight_examples(list(prepared.train_augmented), n=n_examples)
    device = torch.device("cpu")
    model = load_four_way_model(model_id)
    model.to(device)
    assert_ready_to_train(model)
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    batch = batch_encode(examples, tokenizer, max_length=max_length)
    # 过拟合检查用均匀权重；正式训练仍用 prepare 里的 balanced 权重。
    weights = class_weight_tensor([1.0] * 4)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.0)
    amp = choose_amp(device)
    scaler = make_grad_scaler(amp, device)

    history: list[dict[str, float | int]] = []
    print(
        f"过拟合检查：{n_examples} 条样例，{steps} 步，lr={lr}，"
        f"device={device}，amp={amp.name}"
    )
    print("标签：", [row["label"] for row in examples])
    for step in range(1, steps + 1):
        loss = train_step(
            model,
            batch,
            optimizer,
            class_weights=weights,
            autocast_dtype=amp.dtype,
            scaler=scaler,
        )
        history.append({"step": step, "loss": loss})
        if step == 1 or step % 5 == 0 or step == steps:
            print(f"第 {step:>3} 步   loss = {loss:.4f}")

    final = history[-1]["loss"]
    ok = final < LOSS_OK_BELOW
    print(
        f"最终 loss = {final:.4f}  "
        f"{'OK（已接近 0，这 8 条基本背下来了）' if ok else '未降到接近 0，先查代码/精度'}"
    )
    return {
        "n_examples": n_examples,
        "steps": steps,
        "lr": lr,
        "final_loss": final,
        "ok": ok,
        "history": history,
        "labels": [row["label"] for row in examples],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=Path, default=Path("data/pairs.jsonl"))
    parser.add_argument("--steps", type=int, default=DEFAULT_STEPS)
    parser.add_argument("--lr", type=float, default=DEFAULT_LR)
    parser.add_argument("--n", type=int, default=DEFAULT_N_EXAMPLES)
    parser.add_argument("--out", type=Path, default=None, help="把结果 JSON 写到此路径")
    args = parser.parse_args(argv)
    result = run_overfit(pairs_path=args.pairs, steps=args.steps, lr=args.lr, n_examples=args.n)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
