"""比对标签稳定性：同一批冻结主张，交给比对器反复判，看多数票和一致率。

None（比对失败）也算一种标签，不丢弃。这样「偶尔失败」会体现在一致率里，不会被悄悄忽略。
"""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import combinations

from crossfire.application.ports import ClaimPairer
from crossfire.domain import Claim, Relation
from crossfire.domain.evals import ConsistencyInput
from crossfire.domain.pricing import ModelPrice

PairerFor = Callable[[str], ClaimPairer]


@dataclass(frozen=True)
class PairTrial:
    """一对主张在一次重复里的比对结果。relation 为 None 表示这次失败。"""

    relation: Relation | None
    nature: str | None


@dataclass(frozen=True)
class PairSummary:
    case_id: str
    a_url: str
    b_url: str
    a_claim: str
    b_claim: str
    trials: tuple[PairTrial, ...]
    majority: Relation | None
    majority_count: int

    @property
    def unanimous(self) -> bool:
        return self.majority_count == len(self.trials)

    @property
    def agreement_rate(self) -> float:
        return self.majority_count / len(self.trials)


@dataclass(frozen=True)
class ModelConsistency:
    model: str
    pairs: tuple[PairSummary, ...]
    input_tokens: int
    output_tokens: int
    requests: int
    cost_usd: float

    @property
    def overall_agreement(self) -> float:
        total = sum(len(pair.trials) for pair in self.pairs)
        agreed = sum(pair.majority_count for pair in self.pairs)
        return agreed / total if total else 0.0

    def confusion(self) -> Counter[tuple[str, str]]:
        """多数票标签 vs 某次少数票标签。只统计跟多数票不一致的那几次。"""
        counts: Counter[tuple[str, str]] = Counter()
        for pair in self.pairs:
            majority = label_name(pair.majority)
            for trial in pair.trials:
                name = label_name(trial.relation)
                if name != majority:
                    counts[(majority, name)] += 1
        return counts


def estimate_pair_requests(inputs: Sequence[ConsistencyInput], repeats: int, models: Sequence[str]) -> int:
    return sum(pair_count(item.claims) for item in inputs) * repeats * len(models)


def estimate_pair_cost(
    inputs: Sequence[ConsistencyInput],
    repeats: int,
    models: Sequence[str],
    prices: dict[str, ModelPrice],
    *,
    avg_input: int,
    avg_output: int,
) -> float:
    pairs = sum(pair_count(item.claims) for item in inputs)
    return sum(
        prices[model].cost_usd(pairs * repeats * avg_input, pairs * repeats * avg_output) for model in models
    )


def majority_label(labels: Sequence[Relation | None]) -> tuple[Relation | None, int]:
    """多数票。None 是一种标签。平票时按标签名排序取第一个，结果确定。"""
    if not labels:
        raise ValueError("没有标签")
    counts = Counter(labels)
    best = max(counts.values())
    winners = sorted((label for label, count in counts.items() if count == best), key=label_name)
    return winners[0], best


def cross_model_agreement(reference: ModelConsistency, other: ModelConsistency) -> float:
    """两个模型多数票一致的配对比例。按 (case, url 对) 对齐；reference 有而 other 没有的算不一致。"""
    by_key = {(pair.case_id, pair.a_url, pair.b_url): pair.majority for pair in other.pairs}
    if not reference.pairs:
        return 0.0
    matched = sum(
        1 for pair in reference.pairs if by_key.get((pair.case_id, pair.a_url, pair.b_url)) == pair.majority
    )
    return matched / len(reference.pairs)


def pair_count(claims: Sequence[Claim]) -> int:
    n = len(claims)
    return n * (n - 1) // 2


def label_name(relation: Relation | None) -> str:
    return "None" if relation is None else relation.value


class MeasureConsistency:
    def __init__(self, pairer_for: PairerFor) -> None:
        self._pairer_for = pairer_for

    def execute(
        self,
        inputs: Sequence[ConsistencyInput],
        models: Sequence[str],
        repeats: int,
        prices: dict[str, ModelPrice],
    ) -> dict[str, ModelConsistency]:
        if repeats < 1:
            raise ValueError("repeats 必须是正整数")
        return {model: self._run_model(model, inputs, repeats, prices[model]) for model in models}

    def _run_model(
        self,
        model: str,
        inputs: Sequence[ConsistencyInput],
        repeats: int,
        price: ModelPrice,
    ) -> ModelConsistency:
        pairer = self._pairer_for(model)
        trials_by_pair: dict[tuple[str, str, str], list[PairTrial]] = {}
        texts: dict[tuple[str, str, str], tuple[str, str]] = {}
        input_tokens = output_tokens = requests = 0
        for item in inputs:
            claim_pairs = list(combinations(item.claims, 2))
            for _ in range(repeats):
                results = pairer.pair_all(item.question, claim_pairs, item.as_of)
                for (a, b), pair in zip(claim_pairs, results, strict=True):
                    key = (item.case_id, a.source_url, b.source_url)
                    texts[key] = (a.text or "", b.text or "")
                    trials_by_pair.setdefault(key, []).append(PairTrial(relation=pair.relation, nature=pair.nature))
                    input_tokens += pair.usage.input_tokens
                    output_tokens += pair.usage.output_tokens
                    requests += pair.usage.requests or 0
        summaries = tuple(
            _summarize(case_id, a_url, b_url, texts[(case_id, a_url, b_url)], trials)
            for (case_id, a_url, b_url), trials in sorted(trials_by_pair.items())
        )
        return ModelConsistency(
            model=model,
            pairs=summaries,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            requests=requests,
            cost_usd=price.cost_usd(input_tokens, output_tokens),
        )


def _summarize(
    case_id: str,
    a_url: str,
    b_url: str,
    texts: tuple[str, str],
    trials: list[PairTrial],
) -> PairSummary:
    majority, count = majority_label([trial.relation for trial in trials])
    return PairSummary(
        case_id=case_id,
        a_url=a_url,
        b_url=b_url,
        a_claim=texts[0],
        b_claim=texts[1],
        trials=tuple(trials),
        majority=majority,
        majority_count=count,
    )
