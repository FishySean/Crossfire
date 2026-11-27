"""从批量运行（和可选的一致性实验）导出配对训练数据。

切分按题目，不按配对：同一道题的所有配对必须落在同一个集合。
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from crossfire.application.use_cases.measure_consistency import ModelConsistency, majority_label
from crossfire.domain import BankQuestion, Relation, RunResult
from crossfire.domain.bank import QuestionCategory

# 跟评测集是同一问题：只能进测试集，不能进训练集。
EVAL_OVERLAP_IDS = frozenset({"python-latest-stable", "nodejs-lts-version"})
DEFAULT_SEED = "crossfire-5c2-2026-11-20"
DEFAULT_TRAIN_RATIO = 0.8


@dataclass(frozen=True)
class VoteRecord:
    model: str
    relation: Relation | None
    source: str


@dataclass(frozen=True)
class PairExample:
    question_id: str
    question: str
    category: QuestionCategory
    claim_a: str
    claim_b: str
    published_date_a: str | None
    published_date_b: str | None
    a_url: str
    b_url: str
    as_of: str
    label: Relation | None
    votes: tuple[VoteRecord, ...]
    agreement: float | None
    provenance: Mapping[str, object]
    split: str

    def to_jsonl_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "category": self.category.value,
            "claim_a": self.claim_a,
            "claim_b": self.claim_b,
            "published_date_a": self.published_date_a,
            "published_date_b": self.published_date_b,
            "a_url": self.a_url,
            "b_url": self.b_url,
            "as_of": self.as_of,
            "label": None if self.label is None else self.label.value,
            "votes": [
                {
                    "model": vote.model,
                    "relation": None if vote.relation is None else vote.relation.value,
                    "source": vote.source,
                }
                for vote in self.votes
            ],
            "agreement": self.agreement,
            "provenance": dict(self.provenance),
            "split": self.split,
        }


@dataclass(frozen=True)
class DatasetSplit:
    train_ids: tuple[str, ...]
    test_ids: tuple[str, ...]
    seed: str
    train_ratio: float


@dataclass(frozen=True)
class DatasetExport:
    examples: tuple[PairExample, ...]
    split: DatasetSplit

    @property
    def train(self) -> tuple[PairExample, ...]:
        return tuple(item for item in self.examples if item.split == "train")

    @property
    def test(self) -> tuple[PairExample, ...]:
        return tuple(item for item in self.examples if item.split == "test")


def split_question_ids(
    question_ids: Sequence[str],
    *,
    seed: str = DEFAULT_SEED,
    train_ratio: float = DEFAULT_TRAIN_RATIO,
    force_test: frozenset[str] = EVAL_OVERLAP_IDS,
    force_train: frozenset[str] = frozenset(),
    freeze_test_ids: frozenset[str] | None = None,
) -> DatasetSplit:
    """按题目切分。force_test 里的题固定进测试集；其余按稳定哈希分流。

    freeze_test_ids：冻结已有测试题（第 10 步扩训练数据时用），新题全部进 train，
    不重算旧题归属，保证测试集 89 对不变。
    """
    if not 0.0 < train_ratio < 1.0:
        raise ValueError("train_ratio 必须在 (0, 1) 之间")
    all_ids = set(question_ids)
    if freeze_test_ids is not None:
        frozen_test = frozenset(qid for qid in freeze_test_ids if qid in all_ids)
        train_ids = tuple(sorted((all_ids - frozen_test) | (force_train & all_ids)))
        # force_train 不得覆盖冻结测试题
        leaked = set(train_ids) & frozen_test
        if leaked:
            raise RuntimeError(f"冻结测试题被写进训练集：{sorted(leaked)}")
        test_ids = tuple(sorted(frozen_test | (force_test & all_ids)))
        overlap = set(train_ids) & set(test_ids)
        if overlap:
            raise RuntimeError(f"同一道题被切到两个集合：{sorted(overlap)}")
        return DatasetSplit(
            train_ids=train_ids,
            test_ids=test_ids,
            seed=seed,
            train_ratio=train_ratio,
        )

    remaining = sorted(
        qid for qid in question_ids if qid not in force_test and qid not in force_train
    )
    # 稳定伪随机：同一 seed 永远得到同一顺序。
    ordered = sorted(remaining, key=lambda qid: sha256(f"{seed}:{qid}".encode()).hexdigest())
    train_n = int(round(len(ordered) * train_ratio))
    # 至少留 1 道测试题（若还有可分的题）。
    if ordered and train_n >= len(ordered):
        train_n = len(ordered) - 1
    if ordered and train_n < 1 and len(ordered) > 1:
        train_n = 1
    train_ids = tuple(sorted(set(ordered[:train_n]) | (force_train & all_ids)))
    test_ids = tuple(sorted(set(ordered[train_n:]) | (force_test & all_ids)))
    # 变异防护：评测重叠题绝不能进训练集。
    leaked = set(train_ids) & force_test
    if leaked:
        raise RuntimeError(f"评测重叠题进了训练集：{sorted(leaked)}")
    overlap = set(train_ids) & set(test_ids)
    if overlap:
        raise RuntimeError(f"同一道题被切到两个集合：{sorted(overlap)}")
    return DatasetSplit(train_ids=train_ids, test_ids=test_ids, seed=seed, train_ratio=train_ratio)


def export_pair_dataset(
    bank: Sequence[BankQuestion],
    runs: Mapping[str, RunResult],
    *,
    sonnet_consistency: ModelConsistency | None = None,
    split: DatasetSplit | None = None,
    seed: str = DEFAULT_SEED,
    pair_model: str = "claude-sonnet-4-6",
) -> DatasetExport:
    by_id = {question.id: question for question in bank}
    missing = sorted(set(by_id) - set(runs))
    if missing:
        raise ValueError(f"缺少批量运行结果：{missing}")

    sonnet_votes = _index_consistency_votes(sonnet_consistency) if sonnet_consistency else {}
    question_ids = sorted(by_id)
    split = split or split_question_ids(question_ids, seed=seed)
    split_of = {qid: "train" for qid in split.train_ids}
    split_of.update({qid: "test" for qid in split.test_ids})

    examples: list[PairExample] = []
    for question_id, result in sorted(runs.items()):
        bank_question = by_id[question_id]
        claims = {claim.source_url: claim for claim in result.claims if claim.answered and claim.text}
        for pair in result.pairs:
            claim_a = claims.get(pair.a_url)
            claim_b = claims.get(pair.b_url)
            if claim_a is None or claim_b is None or not claim_a.text or not claim_b.text:
                continue
            votes = [
                VoteRecord(model=pair_model, relation=pair.relation, source="batch"),
            ]
            extra = sonnet_votes.get((question_id, _pair_key(pair.a_url, pair.b_url)), ())
            votes.extend(extra)
            labels = [vote.relation for vote in votes]
            if len(labels) == 1:
                label = labels[0]
                agreement: float | None = None
            else:
                label, count = majority_label(labels)
                agreement = count / len(labels)
            examples.append(
                PairExample(
                    question_id=question_id,
                    question=bank_question.text,
                    category=bank_question.category,
                    claim_a=claim_a.text,
                    claim_b=claim_b.text,
                    published_date_a=claim_a.published_date,
                    published_date_b=claim_b.published_date,
                    a_url=pair.a_url,
                    b_url=pair.b_url,
                    as_of="" if result.as_of is None else result.as_of.isoformat(),
                    label=label,
                    votes=tuple(votes),
                    agreement=agreement,
                    provenance={
                        "pair_model": pair_model,
                        "prompt_versions": {
                            name: prov.prompt_version
                            for name, prov in (result.provenance or {}).items()
                        },
                        "run_started_at": result.started_at.isoformat(),
                        "mode": result.mode.value,
                    },
                    split=split_of[question_id],
                )
            )
    return DatasetExport(examples=tuple(examples), split=split)


def dataset_readme(export: DatasetExport) -> str:
    examples = export.examples
    by_label = Counter(None if item.label is None else item.label.value for item in examples)
    by_cat = Counter(item.category.value for item in examples)
    train_cat = Counter(item.category.value for item in export.train)
    test_cat = Counter(item.category.value for item in export.test)
    contradict = by_label.get(Relation.CONTRADICT.value, 0)
    contradict_ratio = contradict / len(examples) if examples else 0.0
    lines = [
        "# Crossfire 配对训练数据",
        "",
        f"- 总配对数：{len(examples)}",
        f"- 标签分布：{dict(by_label)}",
        f"- 题目类别分布（按配对计）：{dict(by_cat)}",
        f"- 训练集：{len(export.train)} 条配对，题目 {list(export.split.train_ids)}",
        f"- 测试集：{len(export.test)} 条配对，题目 {list(export.split.test_ids)}",
        f"- 训练集类别比例：{dict(train_cat)}",
        f"- 测试集类别比例：{dict(test_cat)}",
        f"- 切分种子：`{export.split.seed}`，目标训练比例 {export.split.train_ratio}",
        f"- 评测重叠题（强制测试集）：{sorted(EVAL_OVERLAP_IDS)}",
        "",
    ]
    if contradict_ratio < 0.10:
        lines.append(
            f"**注意：contradict 仅占 {contradict_ratio:.1%}（{contradict}/{len(examples)}），少于 10%。"
            "这会影响训练方法（可能需要过采样或 class weight）。**"
        )
        lines.append("")
    lines += [
        "## 字段",
        "",
        "- `label`：Sonnet 多数票（做过一致性的配对）或批量运行那一票",
        "- `votes`：全部投票；`agreement` 为一致比例，**只有 1 票时为 null**（不是 1.0）",
        "- `design_note` 不会出现在本文件里",
        "",
    ]
    return "\n".join(lines)


def _pair_key(a_url: str, b_url: str) -> tuple[str, str]:
    return (a_url, b_url) if a_url <= b_url else (b_url, a_url)


def _index_consistency_votes(result: ModelConsistency) -> dict[tuple[str, tuple[str, str]], tuple[VoteRecord, ...]]:
    indexed: dict[tuple[str, tuple[str, str]], tuple[VoteRecord, ...]] = {}
    for pair in result.pairs:
        key = (pair.case_id, _pair_key(pair.a_url, pair.b_url))
        indexed[key] = tuple(
            VoteRecord(model=result.model, relation=trial.relation, source=f"consistency:{index}")
            for index, trial in enumerate(pair.trials, start=1)
        )
    return indexed
