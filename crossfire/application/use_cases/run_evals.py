from collections.abc import Callable
from dataclasses import dataclass

from crossfire.application.use_cases.verify_question import SavedRun, VerifyQuestion
from crossfire.domain import Question
from crossfire.domain.evals import EvalCase, Grade

type VerifierFor = Callable[[EvalCase, Question], VerifyQuestion]


@dataclass(frozen=True)
class Attempt:
    saved: SavedRun
    grade: Grade


@dataclass(frozen=True)
class CaseOutcome:
    case: EvalCase
    attempts: tuple[Attempt, ...]

    @property
    def passed(self) -> bool:
        """repeats 次全对才算通过：同一个快照同一个 prompt，模型也会时对时错，一次通过可能只是运气。"""
        return all(attempt.grade.passed for attempt in self.attempts)


def estimate_requests(case: EvalCase, question: Question) -> int:
    """上限：每个来源提取一次，两两比对，判决一次，乘以重复次数。不算重试。"""
    sources = len(question.sources)
    return (sources + sources * (sources - 1) // 2 + 1) * case.repeats


class RunEvals:
    """把一道评测题按 repeats 跑几遍，每遍用标准答案的规则判分。

    verifier_for 由组合根提供，必须只读这道题的冻结快照：评测永远不触发实时抓取。
    """

    def __init__(self, verifier_for: VerifierFor) -> None:
        self._verifier_for = verifier_for

    def execute(self, case: EvalCase, question: Question, on_attempt: Callable[[Attempt], None] | None = None) -> CaseOutcome:
        if question.id != case.question_id:
            raise ValueError(f"评测题 {case.id} 对应的问题是 {case.question_id}，收到的是 {question.id}")
        attempts: list[Attempt] = []
        for _ in range(case.repeats):
            saved = self._verifier_for(case, question).execute(question)
            attempt = Attempt(saved=saved, grade=case.grade(saved.result.judgment.answer))
            attempts.append(attempt)
            if on_attempt:
                on_attempt(attempt)
        return CaseOutcome(case=case, attempts=tuple(attempts))
