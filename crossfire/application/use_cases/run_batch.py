"""题库批量查证：cached 模式跑完整流水线，支持断点续跑。"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from crossfire.application.use_cases.verify_question import SavedRun, VerifyQuestion
from crossfire.domain import BankQuestion, Question
from crossfire.domain.pricing import ModelPrice

VerifierFor = Callable[[Question], VerifyQuestion]
ProgressSaver = Callable[[list[str]], None]


@dataclass(frozen=True)
class BatchEstimate:
    questions: int
    extracts: int
    pairs: int
    judges: int
    anthropic_usd: float

    @property
    def requests(self) -> int:
        return self.extracts + self.pairs + self.judges


def estimate_batch(
    questions: Sequence[BankQuestion],
    *,
    price: ModelPrice,
    extract_in: int = 6000,
    extract_out: int = 180,
    pair_in: int = 2700,
    pair_out: int = 200,
    judge_in: int = 4000,
    judge_out: int = 850,
) -> BatchEstimate:
    extracts = sum(len(question.sources) for question in questions)
    pairs = sum(_pair_count(len(question.sources)) for question in questions)
    judges = len(questions)
    usd = (
        price.cost_usd(extracts * extract_in, extracts * extract_out)
        + price.cost_usd(pairs * pair_in, pairs * pair_out)
        + price.cost_usd(judges * judge_in, judges * judge_out)
    )
    return BatchEstimate(questions=len(questions), extracts=extracts, pairs=pairs, judges=judges, anthropic_usd=usd)


def _pair_count(n: int) -> int:
    return n * (n - 1) // 2


class RunBatch:
    """对题库逐题跑 VerifyQuestion。已完成的 id 跳过。"""

    def __init__(
        self,
        verifier_for: VerifierFor,
        *,
        on_progress: ProgressSaver | None = None,
        on_saved: Callable[[BankQuestion, SavedRun], None] | None = None,
    ) -> None:
        self._verifier_for = verifier_for
        self._on_progress = on_progress
        self._on_saved = on_saved

    def execute(
        self,
        questions: Sequence[BankQuestion],
        *,
        done_ids: Sequence[str] = (),
    ) -> list[tuple[BankQuestion, SavedRun]]:
        finished = set(done_ids)
        results: list[tuple[BankQuestion, SavedRun]] = []
        progress = list(done_ids)
        for bank_question in questions:
            if bank_question.id in finished:
                continue
            pipeline = bank_question.to_pipeline_question()
            if bank_question.design_note and bank_question.design_note in pipeline.text:
                raise RuntimeError(f"{bank_question.id}: design_note 泄漏进了题目正文")
            saved = self._verifier_for(pipeline).execute(pipeline)
            results.append((bank_question, saved))
            progress.append(bank_question.id)
            finished.add(bank_question.id)
            if self._on_saved:
                self._on_saved(bank_question, saved)
            if self._on_progress:
                self._on_progress(progress)
        return results
