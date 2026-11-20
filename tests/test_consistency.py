"""比对标签稳定性：多数票把 None 算作一类；费用估算用登记过的单价。"""

from datetime import date

import pytest

from crossfire.application.use_cases.measure_consistency import (
    MeasureConsistency,
    ModelConsistency,
    PairSummary,
    PairTrial,
    cross_model_agreement,
    estimate_pair_requests,
    majority_label,
)
from crossfire.config import MODEL_PRICES, Settings, load_consistency_inputs
from crossfire.domain import Claim, Question, Relation, Source, Tier, Usage
from crossfire.domain.evals import ConsistencyInput
from crossfire.domain.pricing import ModelPrice


def test_majority_counts_none_as_a_label():
    # 第 5b 步有意要求的变异目标：如果把 None 丢掉，这里会变成 contradict 3 票。
    labels = [Relation.CONTRADICT, Relation.CONTRADICT, None, None, None]
    assert majority_label(labels) == (None, 3)


def test_majority_tie_is_deterministic():
    labels = [Relation.AGREE, Relation.CONTRADICT, Relation.AGREE, Relation.CONTRADICT, None]
    # agree×2 contradict×2 None×1 → 平票取名字排序靠前的 agree
    assert majority_label(labels)[0] is Relation.AGREE


def test_estimate_pair_requests_multiplies_pairs_repeats_models():
    claims = (
        Claim("https://a/", Tier.PRIMARY, "1", "e", None, None, 1.0, Usage(1, 1, 1)),
        Claim("https://b/", Tier.PRIMARY, "2", "e", None, None, 1.0, Usage(1, 1, 1)),
        Claim("https://c/", Tier.NEWS, "3", "e", None, None, 1.0, Usage(1, 1, 1)),
    )
    item = ConsistencyInput(
        case_id="x",
        question=Question("x", "q", tuple(Source(c.source_url, c.tier) for c in claims)),
        as_of=date(2026, 9, 12),
        claims=claims,
        source="t",
    )
    assert estimate_pair_requests([item], repeats=5, models=["m1", "m2"]) == 3 * 5 * 2


def test_cross_model_agreement_aligns_by_case_and_urls():
    def summary(case, a, b, label):
        return PairSummary(case, a, b, "A", "B", (PairTrial(label, "n"),) * 5, label, 5)

    sonnet = ModelConsistency(
        "s",
        (summary("c", "u1", "u2", Relation.CONTRADICT), summary("c", "u1", "u3", Relation.AGREE)),
        0,
        0,
        0,
        0.0,
    )
    haiku = ModelConsistency(
        "h",
        (summary("c", "u1", "u2", Relation.CONTRADICT), summary("c", "u1", "u3", Relation.CONTRADICT)),
        0,
        0,
        0,
        0.0,
    )
    assert cross_model_agreement(sonnet, haiku) == 0.5


def test_consistency_inputs_are_loadable():
    settings = Settings.from_env()
    inputs = load_consistency_inputs(settings)
    assert {item.case_id for item in inputs} >= {"python-2026-11", "nodejs-2026-09", "tokyo-2026-09", "python-2026-09"}
    assert all(len(item.claims) >= 2 for item in inputs)


def test_unknown_model_price_is_a_loud_settings_error():
    settings = Settings.from_env()
    with pytest.raises(Exception, match="不知道模型"):
        settings.price_for("claude-made-up-9")


def test_model_prices_match_the_documented_defaults():
    assert MODEL_PRICES["claude-sonnet-4-6"] == ModelPrice(3.0, 15.0)
    assert MODEL_PRICES["claude-haiku-4-5"] == ModelPrice(1.0, 5.0)
    assert abs(MODEL_PRICES["claude-sonnet-4-6"].cost_usd(1_000_000, 1_000_000) - 18.0) < 1e-9
