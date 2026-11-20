"""从已有运行结果汇总每步耗时、请求、token 和估算费用。本身不调模型。"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from crossfire.domain import RunResult
from crossfire.domain.pricing import ModelPrice


@dataclass(frozen=True)
class StepBench:
    name: str
    calls: int
    requests: int | None
    input_tokens: int
    output_tokens: int
    seconds: float
    cost_usd: float


@dataclass(frozen=True)
class RunBench:
    case_id: str
    source: str
    model: str
    steps: tuple[StepBench, ...]
    elapsed_seconds: float

    @property
    def cost_usd(self) -> float:
        return sum(step.cost_usd for step in self.steps)


@dataclass(frozen=True)
class BenchReport:
    runs: tuple[RunBench, ...]

    def totals_by_step(self) -> tuple[StepBench, ...]:
        buckets: dict[str, list[StepBench]] = defaultdict(list)
        for run in self.runs:
            for step in run.steps:
                buckets[step.name].append(step)
        return tuple(_merge(name, items) for name, items in sorted(buckets.items()))

    @property
    def total_cost_usd(self) -> float:
        return sum(run.cost_usd for run in self.runs)

    @property
    def total_seconds(self) -> float:
        return sum(run.elapsed_seconds for run in self.runs)

    def slowest_step(self) -> StepBench | None:
        steps = self.totals_by_step()
        return max(steps, key=lambda step: step.seconds) if steps else None

    def costliest_step(self) -> StepBench | None:
        steps = self.totals_by_step()
        return max(steps, key=lambda step: step.cost_usd) if steps else None


def bench_runs(
    labeled: Sequence[tuple[str, str, RunResult]],
    prices: dict[str, ModelPrice],
    default_model: str,
) -> BenchReport:
    """labeled 是 (case_id, source_path, result)。模型优先取 provenance，没有就用 default_model。"""
    runs = tuple(_one(case_id, source, result, prices, default_model) for case_id, source, result in labeled)
    return BenchReport(runs=runs)


def _one(
    case_id: str,
    source: str,
    result: RunResult,
    prices: dict[str, ModelPrice],
    default_model: str,
) -> RunBench:
    model = default_model
    if result.provenance:
        models = {item.model for item in result.provenance.values()}
        if len(models) == 1:
            model = next(iter(models))
    price = prices[model]
    steps = tuple(
        StepBench(
            name=name,
            calls=step.calls,
            requests=step.requests,
            input_tokens=step.input_tokens or 0,
            output_tokens=step.output_tokens or 0,
            seconds=step.seconds,
            cost_usd=price.cost_usd(step.input_tokens or 0, step.output_tokens or 0),
        )
        for name, step in result.steps.items()
    )
    return RunBench(case_id=case_id, source=source, model=model, steps=steps, elapsed_seconds=result.elapsed_seconds)


def _merge(name: str, items: Sequence[StepBench]) -> StepBench:
    requests = [step.requests for step in items]
    return StepBench(
        name=name,
        calls=sum(step.calls for step in items),
        requests=None if any(value is None for value in requests) else sum(value or 0 for value in requests),
        input_tokens=sum(step.input_tokens for step in items),
        output_tokens=sum(step.output_tokens for step in items),
        seconds=sum(step.seconds for step in items),
        cost_usd=sum(step.cost_usd for step in items),
    )
