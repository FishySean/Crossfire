"""bench：从已有运行汇总步骤费用，不调模型。"""

from datetime import UTC, date, datetime

from crossfire.application.use_cases.bench_runs import bench_runs
from crossfire.config import MODEL_PRICES
from crossfire.domain import Judgment, Mode, Question, RunResult, Source, StepStats, Tier, Usage


def test_bench_sums_steps_and_picks_the_slowest_and_costliest():
    question = Question("q", "text", (Source("https://a/", Tier.PRIMARY),))
    result = RunResult(
        question=question,
        mode=Mode.CACHED,
        started_at=datetime(2026, 9, 12, tzinfo=UTC),
        as_of=date(2026, 9, 12),
        elapsed_seconds=40.0,
        steps={
            "fetch": StepStats(calls=2, seconds=1.0),
            "extract": StepStats(calls=2, seconds=20.0, input_tokens=10_000, output_tokens=200, requests=2),
            "pair": StepStats(calls=1, seconds=5.0, input_tokens=2_000, output_tokens=100, requests=1),
            "judge": StepStats(calls=1, seconds=14.0, input_tokens=3_000, output_tokens=500, requests=1),
        },
        provenance=None,
        pages=(),
        claims=(),
        pairs=(),
        judgment=Judgment(None, None, None, (), (), Usage(0, 0, 0)),
    )
    report = bench_runs([("case", "path.json", result)], MODEL_PRICES, "claude-sonnet-4-6")
    assert report.slowest_step().name == "extract"
    assert report.costliest_step().name == "extract"
    assert abs(report.total_cost_usd - MODEL_PRICES["claude-sonnet-4-6"].cost_usd(15_000, 800)) < 1e-9
