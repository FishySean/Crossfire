"""从训练集里再按题目切出验证集。

必须按题目切、不能按配对切：同一道题的配对彼此相关（同一批来源、同一问法）。
若把同一题的配对拆进训练和验证，验证分数会被「见过这道题」抬高，停训时机失真。

验证集大约 2 道题，主要用来看「总体加权损失」何时回升（早停），
不是用来精确评估每个类别。因此：
- 必须：contradict ≥ 2、same_question_different_scope ≥ 2（能看见走势即可）
- 优先：从训练集拿走的难题（contradict + scope + unrelated）总数最少
- 并列时：用固定种子打破平局

不要把 mysql 这类「一道题占六成矛盾」的大户整题挪进验证集。
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from training.labels import LABELS

# 验证集里这两类至少各几条（只为能看见走势，不是为精确评估）。
MIN_VAL_LABEL_COUNTS: dict[str, int] = {
    "contradict": 2,
    "same_question_different_scope": 2,
}
# 从训练里挪走时要尽量少动的「难题」标签。
HARD_LABELS = frozenset(
    {
        "contradict",
        "same_question_different_scope",
        "unrelated",
    }
)
DEFAULT_VAL_SEED = "crossfire-val-2026-11-20"
DEFAULT_N_VAL_QUESTIONS = 2


@dataclass(frozen=True)
class SplitByQuestion:
    """train / val / test 的题目 id，以及为何选中验证题。"""

    train_ids: tuple[str, ...]
    val_ids: tuple[str, ...]
    test_ids: tuple[str, ...]
    seed: str
    n_val_questions: int
    n_valid_combos: int
    hard_labels_taken: int
    reason: str

    def label_counts(
        self, rows: Sequence[Mapping[str, Any]]
    ) -> dict[str, Counter[str]]:
        buckets = {"train": Counter(), "val": Counter(), "test": Counter()}
        id_to_split = {
            **{qid: "train" for qid in self.train_ids},
            **{qid: "val" for qid in self.val_ids},
            **{qid: "test" for qid in self.test_ids},
        }
        for row in rows:
            split = id_to_split[str(row["question_id"])]
            buckets[split][str(row["label"])] += 1
        return buckets


def _label_counts_for(
    by_question: Mapping[str, Sequence[Mapping[str, Any]]],
    question_ids: Sequence[str],
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for qid in question_ids:
        for row in by_question[qid]:
            counts[str(row["label"])] += 1
    return counts


def _meets_min_counts(counts: Counter[str], mins: Mapping[str, int]) -> bool:
    return all(counts.get(label, 0) >= need for label, need in mins.items())


def _hard_taken(counts: Counter[str]) -> int:
    return sum(counts.get(label, 0) for label in HARD_LABELS)


def _combo_key(seed: str, combo: Sequence[str]) -> str:
    """同一种子下可复现的排序键；不是密码学用途。"""
    payload = f"{seed}|{'|'.join(sorted(combo))}"
    return hashlib.sha256(payload.encode()).hexdigest()


def choose_val_question_ids(
    train_rows: Sequence[Mapping[str, Any]],
    *,
    n_questions: int = DEFAULT_N_VAL_QUESTIONS,
    seed: str = DEFAULT_VAL_SEED,
    min_label_counts: Mapping[str, int] | None = None,
) -> tuple[tuple[str, ...], int, int, str]:
    """选验证题：先满足最少标签条数，再最少挪走难题，并列用种子。

    返回 (val_ids, 合格组合数, 挪走的难题条数, 选型理由)。
    """
    if n_questions < 1:
        raise ValueError("n_questions 至少为 1")
    mins = dict(min_label_counts or MIN_VAL_LABEL_COUNTS)

    by_question: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in train_rows:
        by_question[str(row["question_id"])].append(row)
    question_ids = sorted(by_question)

    if len(question_ids) < n_questions:
        raise ValueError(
            f"训练题只有 {len(question_ids)} 道，无法切出 {n_questions} 道验证题"
        )

    valid: list[tuple[str, ...]] = []
    for combo in itertools.combinations(question_ids, n_questions):
        counts = _label_counts_for(by_question, combo)
        if _meets_min_counts(counts, mins):
            valid.append(combo)

    if not valid:
        raise ValueError(
            f"没有任何 {n_questions} 道题的组合能同时满足最少标签数 {mins}。"
            "请减少约束或增加题目。"
        )

    # 主键：拿走的难题越少越好；并列再用种子哈希；再并列用题目 id。
    valid.sort(
        key=lambda combo: (
            _hard_taken(_label_counts_for(by_question, combo)),
            _combo_key(seed, combo),
            combo,
        )
    )
    chosen = valid[0]
    counts = _label_counts_for(by_question, chosen)
    hard = _hard_taken(counts)
    n_tied = sum(
        1
        for combo in valid
        if _hard_taken(_label_counts_for(by_question, combo)) == hard
    )
    reason = (
        f"在 {len(valid)} 组「{n_questions} 道题且 contradict≥"
        f"{mins.get('contradict', 0)}、scope≥"
        f"{mins.get('same_question_different_scope', 0)}」的组合里，"
        f"优先少挪走难题（contradict+scope+unrelated）；"
        f"最少挪走 {hard} 条，并列 {n_tied} 组，种子 {seed!r} 选中 {list(chosen)}；"
        f"验证集标签 {dict(counts)}"
    )
    return chosen, len(valid), hard, reason


def split_train_val_test(
    rows: Sequence[Mapping[str, Any]],
    *,
    n_val_questions: int = DEFAULT_N_VAL_QUESTIONS,
    seed: str = DEFAULT_VAL_SEED,
) -> SplitByQuestion:
    """用 pairs.jsonl 的 split 字段：test 不动；原 train 再切 val。"""
    train_rows = [row for row in rows if row["split"] == "train"]
    test_ids = tuple(sorted({str(row["question_id"]) for row in rows if row["split"] == "test"}))
    val_ids, n_valid, hard, reason = choose_val_question_ids(
        train_rows, n_questions=n_val_questions, seed=seed
    )
    all_train_ids = sorted({str(row["question_id"]) for row in train_rows})
    train_ids = tuple(qid for qid in all_train_ids if qid not in set(val_ids))
    return SplitByQuestion(
        train_ids=train_ids,
        val_ids=tuple(sorted(val_ids)),
        test_ids=test_ids,
        seed=seed,
        n_val_questions=n_val_questions,
        n_valid_combos=n_valid,
        hard_labels_taken=hard,
        reason=reason,
    )


def load_pair_rows(path: str | Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def count_labels(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    raw = Counter(str(row["label"]) for row in rows)
    return {label: int(raw.get(label, 0)) for label in LABELS}
