"""按题目分组的 K 折交叉验证（只动 train 池，永不碰测试集）。"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QuestionFold:
    fold_index: int
    train_ids: tuple[str, ...]
    val_ids: tuple[str, ...]


def _stable_order(question_ids: Sequence[str], seed: str) -> list[str]:
    return sorted(
        question_ids,
        key=lambda qid: hashlib.sha256(f"{seed}|cv|{qid}".encode()).hexdigest(),
    )


def grouped_kfold_by_question(
    rows: Sequence[Mapping[str, Any]],
    *,
    n_folds: int = 5,
    seed: str = "crossfire-cv-2026-11-27",
) -> tuple[QuestionFold, ...]:
    """把题目稳定洗牌后切成 n_folds 折；每折的 val 为该折题目，其余为 train。"""
    if n_folds < 2:
        raise ValueError("n_folds 至少为 2")
    by_q: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_q[str(row["question_id"])].append(row)
    question_ids = _stable_order(sorted(by_q), seed)
    if len(question_ids) < n_folds:
        raise ValueError(
            f"题目只有 {len(question_ids)} 道，无法做 {n_folds} 折分组交叉验证"
        )

    folds: list[list[str]] = [[] for _ in range(n_folds)]
    for index, qid in enumerate(question_ids):
        folds[index % n_folds].append(qid)

    out: list[QuestionFold] = []
    for fold_index, val_ids in enumerate(folds):
        val_set = set(val_ids)
        train_ids = tuple(qid for qid in question_ids if qid not in val_set)
        if not train_ids or not val_ids:
            raise ValueError(f"第 {fold_index} 折 train/val 为空")
        out.append(
            QuestionFold(
                fold_index=fold_index,
                train_ids=train_ids,
                val_ids=tuple(sorted(val_ids)),
            )
        )
    return tuple(out)


def rows_for_ids(
    rows: Sequence[Mapping[str, Any]], ids: Sequence[str]
) -> list[dict[str, Any]]:
    wanted = set(ids)
    return [dict(row) for row in rows if str(row["question_id"]) in wanted]
