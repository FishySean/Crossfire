"""第 7 步：切验证集、A/B 增强、算类别权重。训练脚本只调用这里。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from training.augment import augment_train_with_swaps
from training.class_weights import balanced_class_weights, class_weight_tensor_values
from training.split import (
    DEFAULT_N_VAL_QUESTIONS,
    DEFAULT_VAL_SEED,
    SplitByQuestion,
    count_labels,
    load_pair_rows,
    split_train_val_test,
)


@dataclass(frozen=True)
class PreparedSplits:
    split: SplitByQuestion
    train_rows: tuple[dict[str, Any], ...]
    train_augmented: tuple[dict[str, Any], ...]
    val_rows: tuple[dict[str, Any], ...]
    test_rows: tuple[dict[str, Any], ...]
    class_weights: dict[str, float]
    class_weight_list: tuple[float, ...]

    def counts_table(self) -> dict[str, dict[str, int]]:
        return {
            "train_before_aug": count_labels(self.train_rows),
            "train_after_aug": count_labels(self.train_augmented),
            "val": count_labels(self.val_rows),
            "test": count_labels(self.test_rows),
        }


def _rows_for_ids(
    rows: Sequence[Mapping[str, Any]], ids: Sequence[str]
) -> list[dict[str, Any]]:
    wanted = set(ids)
    return [dict(row) for row in rows if str(row["question_id"]) in wanted]


def prepare_from_pairs(
    pairs_path: Path | str,
    *,
    n_val_questions: int = DEFAULT_N_VAL_QUESTIONS,
    seed: str = DEFAULT_VAL_SEED,
) -> PreparedSplits:
    rows = load_pair_rows(Path(pairs_path))
    # 测试集绝对不能进训练切分逻辑之外的用途；这里只按已有 split 字段读取。
    test_ids_in_file = {str(r["question_id"]) for r in rows if r["split"] == "test"}
    train_pool = [r for r in rows if r["split"] == "train"]
    if any(str(r["question_id"]) in test_ids_in_file for r in train_pool):
        raise RuntimeError("测试集题目混进了训练集，拒绝准备数据")

    split = split_train_val_test(rows, n_val_questions=n_val_questions, seed=seed)
    train_rows = _rows_for_ids(train_pool, split.train_ids)
    val_rows = _rows_for_ids(train_pool, split.val_ids)
    test_rows = [dict(r) for r in rows if r["split"] == "test"]

    # 变异防护：验证/测试不得做 A/B 增强
    augmented = augment_train_with_swaps(train_rows)
    weights = balanced_class_weights(augmented)
    return PreparedSplits(
        split=split,
        train_rows=tuple(train_rows),
        train_augmented=tuple(augmented),
        val_rows=tuple(val_rows),
        test_rows=tuple(test_rows),
        class_weights=weights,
        class_weight_list=tuple(class_weight_tensor_values(weights)),
    )
