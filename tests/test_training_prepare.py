"""第 7 步：按题目切验证集、A/B 只增强训练、类别权重。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from training.augment import augment_train_with_swaps, swap_ab
from training.class_weights import balanced_class_weights
from training.early_stop import EARLY_STOP_METRIC
from training.prepare import prepare_from_pairs
from training.split import choose_val_question_ids, split_train_val_test


def _row(
    qid: str,
    label: str,
    *,
    split: str = "train",
    a: str = "A",
    b: str = "B",
) -> dict:
    return {
        "question_id": qid,
        "question": qid,
        "category": "scope",
        "claim_a": a,
        "claim_b": b,
        "published_date_a": "2020-01-01",
        "published_date_b": "2021-01-01",
        "a_url": f"https://a/{qid}",
        "b_url": f"https://b/{qid}",
        "as_of": "2026-11-20",
        "label": label,
        "split": split,
    }


def _hard_small() -> list[dict]:
    """一道题：刚好 2 contradict + 2 scope（最少占用难题）。"""
    return [
        _row("reef", "contradict", a="r1", b="r2"),
        _row("reef", "contradict", a="r3", b="r4"),
        _row("reef", "same_question_different_scope", a="r5", b="r6"),
        _row("reef", "same_question_different_scope", a="r7", b="r8"),
        _row("reef", "agree", a="r9", b="r10"),
    ]


def _hard_huge() -> list[dict]:
    """一道题：很多 contradict（类似 mysql），不该被优先选进验证。"""
    rows = [_row("mysqlish", "agree", a="m0", b="m1")]
    for i in range(10):
        rows.append(_row("mysqlish", "contradict", a=f"mc{i}a", b=f"mc{i}b"))
    for i in range(4):
        rows.append(
            _row("mysqlish", "same_question_different_scope", a=f"ms{i}a", b=f"ms{i}b")
        )
    return rows


def test_val_split_is_by_question_not_by_pair() -> None:
    # 变异目标：若按配对随机切，同一题会同时出现在 train 和 val。
    rows = (
        _hard_small()
        + [
            _row("all-agree", "agree", a="a1", b="b1"),
            _row("all-agree", "agree", a="a2", b="b2"),
            _row("other", "agree", a="o1", b="o2"),
            _row("t1", "agree", split="test"),
        ]
    )
    split = split_train_val_test(rows, n_val_questions=2, seed="unit-seed")
    assert set(split.val_ids).isdisjoint(split.train_ids)
    assert set(split.val_ids).isdisjoint(split.test_ids)
    for qid in {r["question_id"] for r in rows if r["split"] == "train"}:
        side = "val" if qid in split.val_ids else "train"
        assert qid not in (split.train_ids if side == "val" else split.val_ids)


def test_val_prefers_fewer_hard_labels_over_mysql_sized_question() -> None:
    # 变异目标：若只要求「有标签」再用种子，可能选中 mysqlish 搬走大半 contradict。
    rows = (
        _hard_small()
        + _hard_huge()
        + [
            _row("all-agree", "agree", a="aa1", b="aa2"),
            _row("all-agree", "agree", a="aa3", b="aa4"),
        ]
    )
    val_ids, n_valid, hard, reason = choose_val_question_ids(rows, n_questions=2, seed="s")
    assert n_valid >= 1
    assert "mysqlish" not in val_ids
    assert "reef" in val_ids
    assert hard == 4  # reef 的 2+2，all-agree 不贡献难题
    counts = {r["label"] for r in rows if r["question_id"] in val_ids}
    assert "contradict" in counts and "same_question_different_scope" in counts
    assert "少挪走" in reason or "难题" in reason


def test_val_requires_at_least_two_of_each_hard_label() -> None:
    rows = [
        _row("one-each", "contradict", a="a", b="b"),
        _row("one-each", "same_question_different_scope", a="c", b="d"),
        _row("agree-only", "agree", a="e", b="f"),
    ]
    with pytest.raises(ValueError, match="最少标签"):
        choose_val_question_ids(rows, n_questions=2, seed="s")


def test_ab_swap_only_on_train_and_skips_identical() -> None:
    train = [
        _row("q", "agree", a="hello", b="world"),
        _row("q", "agree", a="same", b="same"),
    ]
    out = augment_train_with_swaps(train)
    assert len(out) == 3  # 两条原样 + 一条交换（identical 跳过）
    swapped = [r for r in out if r.get("augmented") == "swap_ab"]
    assert len(swapped) == 1
    assert swapped[0]["claim_a"] == "world"
    assert swapped[0]["claim_b"] == "hello"
    assert swapped[0]["label"] == "agree"


def test_ab_swap_must_not_touch_val_or_test_in_prepare(tmp_path: Path) -> None:
    # 变异目标：若对 val/test 也做交换，这里会多出行。
    def four(qid: str) -> list[dict]:
        return [
            _row(qid, "agree", a=f"{qid}-a1", b=f"{qid}-b1"),
            _row(qid, "contradict", a=f"{qid}-a2", b=f"{qid}-b2"),
            _row(qid, "contradict", a=f"{qid}-a2b", b=f"{qid}-b2b"),
            _row(qid, "same_question_different_scope", a=f"{qid}-a3", b=f"{qid}-b3"),
            _row(qid, "same_question_different_scope", a=f"{qid}-a3b", b=f"{qid}-b3b"),
            _row(qid, "unrelated", a=f"{qid}-a4", b=f"{qid}-b4"),
        ]

    rows = four("v1") + four("v2") + four("tr") + [_row("te", "agree", split="test", a="e1", b="e2")]
    path = tmp_path / "pairs.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    prepared = prepare_from_pairs(path, n_val_questions=2, seed="prep")
    assert all(r.get("augmented") in (None, "swap_ab") for r in prepared.train_augmented)
    assert all(r.get("augmented") is None for r in prepared.val_rows)
    assert all("augmented" not in r or r.get("augmented") is None for r in prepared.test_rows)
    assert len(prepared.val_rows) == sum(1 for r in rows if r["question_id"] in prepared.split.val_ids)
    assert len(prepared.test_rows) == 1
    assert len(prepared.train_augmented) == len(prepared.train_rows) * 2


def test_class_weights_upweight_rare_labels() -> None:
    rows = (
        [_row("q", "agree", a=f"a{i}", b=f"b{i}") for i in range(8)]
        + [_row("q", "contradict", a="c1", b="c2")]
        + [_row("q", "same_question_different_scope", a="s1", b="s2")]
        + [_row("q", "unrelated", a="u1", b="u2")]
    )
    weights = balanced_class_weights(rows)
    assert weights["agree"] < weights["contradict"]
    assert weights["agree"] < weights["unrelated"]
    assert weights["contradict"] == pytest.approx(11 / 4)
    assert weights["agree"] == pytest.approx(11 / (4 * 8))


def test_swap_preserves_label() -> None:
    row = _row("q", "same_question_different_scope", a="甲", b="乙")
    swapped = swap_ab(row)
    assert swapped["label"] == row["label"]
    assert swapped["claim_a"] == "乙"


def test_early_stop_uses_weighted_val_loss_not_per_class() -> None:
    assert EARLY_STOP_METRIC == "val_weighted_loss"
