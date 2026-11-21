"""A/B 交换增强：只用于训练集。

关系四类在交换 A/B 后标签不变（一致、矛盾、口径不同、无关都对称）。
验证集和测试集不做交换：它们要反映真实分布，不能人为翻倍。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any


def swap_ab(row: Mapping[str, Any]) -> dict[str, Any]:
    """交换主张 A/B（含日期与 URL），标签与问题不变。"""
    out = deepcopy(dict(row))
    out["claim_a"], out["claim_b"] = row["claim_b"], row["claim_a"]
    out["published_date_a"], out["published_date_b"] = (
        row["published_date_b"],
        row["published_date_a"],
    )
    out["a_url"], out["b_url"] = row["b_url"], row["a_url"]
    out["augmented"] = "swap_ab"
    return out


def augment_train_with_swaps(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """原样保留 + 交换版。A 与 B 文本完全相同的不交换（交换后仍是同一条）。"""
    out: list[dict[str, Any]] = []
    for row in rows:
        base = dict(row)
        base.setdefault("augmented", None)
        out.append(base)
        if str(row["claim_a"]).strip() == str(row["claim_b"]).strip():
            continue
        out.append(swap_ab(row))
    return out
