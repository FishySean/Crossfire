"""用正式设置跑几步：切分 → 增强 → 加权损失 → 验证损失。确认流水线通。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from torch.utils.data import DataLoader, Dataset
from transformers import AutoTokenizer

from training.loop import (
    assert_ready_to_train,
    batch_encode,
    class_weight_tensor,
    eval_weighted_loss,
    train_step,
)
from training.prepare import prepare_from_pairs
from training.resize_head import BASE_MODEL_ID, load_four_way_model, training_autocast_dtype


class PairDataset(Dataset):
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict:
        return self.rows[index]


def collate(tokenizer, max_length: int):
    def _collate(rows: list[dict]):
        return batch_encode(rows, tokenizer, max_length=max_length)

    return _collate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=Path, default=Path("data/pairs.jsonl"))
    parser.add_argument("--steps", type=int, default=5, help="只跑几步冒烟")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--lr", type=float, default=2e-5, help="正式训练常用量级")
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    prepared = prepare_from_pairs(args.pairs)
    device = torch.device("cpu")
    model = load_four_way_model(BASE_MODEL_ID)
    model.to(device)
    assert_ready_to_train(model)
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_ID)
    weights = class_weight_tensor(prepared.class_weight_list)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    autocast = training_autocast_dtype(device)

    train_loader = DataLoader(
        PairDataset(list(prepared.train_augmented)),
        batch_size=args.batch_size,
        shuffle=True,
        collate_fn=collate(tokenizer, args.max_length),
    )
    val_batch = batch_encode(list(prepared.val_rows), tokenizer, max_length=args.max_length)

    history = []
    train_iter = iter(train_loader)
    print(
        f"冒烟：train={len(prepared.train_augmented)} val={len(prepared.val_rows)} "
        f"steps={args.steps} lr={args.lr} device={device}"
    )
    print(f"验证题：{list(prepared.split.val_ids)}")
    for step in range(1, args.steps + 1):
        try:
            batch = next(train_iter)
        except StopIteration:
            train_iter = iter(train_loader)
            batch = next(train_iter)
        train_loss = train_step(
            model, batch, optimizer, class_weights=weights, autocast_dtype=autocast
        )
        val_loss = eval_weighted_loss(model, val_batch, class_weights=weights)
        history.append({"step": step, "train_loss": train_loss, "val_weighted_loss": val_loss})
        print(f"第 {step} 步   train_loss={train_loss:.4f}   val_weighted_loss={val_loss:.4f}")

    result = {
        "steps": args.steps,
        "history": history,
        "val_ids": list(prepared.split.val_ids),
        "class_weights": prepared.class_weights,
    }
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("冒烟通过：切分、增强、加权训练、验证损失整条链路无报错。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
