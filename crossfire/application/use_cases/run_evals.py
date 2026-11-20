from collections.abc import Callable, Sequence
from dataclasses import dataclass

from crossfire.application.ports import Clock, VerdictJudge
from crossfire.application.use_cases.verify_question import VerifyQuestion
from crossfire.domain import AsOf, Judgment, Question, RunResult
from crossfire.domain.evals import CaseKind, EvalCase, Grade, JudgeInput

type VerifierFor = Callable[[EvalCase, Question], VerifyQuestion]
type JudgeFor = Callable[[EvalCase], VerdictJudge]
type OnAttempt = Callable[["Attempt"], None]


@dataclass(frozen=True)
class Attempt:
    """一次作答。full 题有整次运行的结果和保存位置；judge 题只有一次判决，source 是那份输入取自哪次运行。"""

    judgment: Judgment
    as_of: AsOf | None
    requests: int | None
    input_tokens: int
    output_tokens: int
    seconds: float
    grade: Grade
    result: RunResult | None = None
    location: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class CaseOutcome:
    case: EvalCase
    attempts: tuple[Attempt, ...]

    @property
    def passed(self) -> bool:
        """repeats 次全对才算通过：同一个快照同一个 prompt，模型也会时对时错，一次通过可能只是运气。"""
        return all(attempt.grade.passed for attempt in self.attempts)


def estimate_requests(case: EvalCase, question: Question, judge_inputs: Sequence[JudgeInput] = ()) -> int:
    """上限，不算重试。full 题：每个来源提取一次，两两比对，判决一次。judge 题：每份输入判决一次。都乘以重复次数。"""
    if case.kind is CaseKind.JUDGE:
        return len(judge_inputs) * case.repeats
    sources = len(question.sources)
    return (sources + sources * (sources - 1) // 2 + 1) * case.repeats


def _check_question(case: EvalCase, question: Question) -> None:
    if question.id != case.question_id:
        raise ValueError(f"评测题 {case.id} 对应的问题是 {case.question_id}，收到的是 {question.id}")


class RunEvals:
    """把一道 full 评测题按 repeats 跑几遍，每遍用标准答案的规则判分。

    verifier_for 由组合根提供，必须只读这道题的冻结快照：评测永远不触发实时抓取。
    """

    def __init__(self, verifier_for: VerifierFor) -> None:
        self._verifier_for = verifier_for

    def execute(self, case: EvalCase, question: Question, on_attempt: OnAttempt | None = None) -> CaseOutcome:
        _check_question(case, question)
        attempts: list[Attempt] = []
        for _ in range(case.repeats):
            saved = self._verifier_for(case, question).execute(question)
            result = saved.result
            grade = case.grade(result.judgment.answer, result.judgment.reasoning)
            if result.as_of != case.as_of:
                grade = grade.failing(f"告诉模型的今天是 {result.as_of}，这道题的快照日期是 {case.as_of}")
            attempt = Attempt(
                judgment=result.judgment,
                as_of=result.as_of,
                requests=result.model_requests,
                input_tokens=result.total_input_tokens,
                output_tokens=result.total_output_tokens,
                seconds=result.elapsed_seconds,
                grade=grade,
                result=result,
                location=saved.location,
            )
            attempts.append(attempt)
            if on_attempt:
                on_attempt(attempt)
        return CaseOutcome(case=case, attempts=tuple(attempts))


class RunJudgeEvals:
    """judge 题：把每份冻结的 claims 和 pairs 交给判决，每份一次请求，按 repeats 重复。

    今天的日期用题目的 as_of：这些输入是那天的快照产出的。
    """

    def __init__(self, judge_for: JudgeFor, clock: Clock) -> None:
        self._judge_for = judge_for
        self._clock = clock

    def execute(
        self,
        case: EvalCase,
        question: Question,
        inputs: Sequence[JudgeInput],
        on_attempt: OnAttempt | None = None,
    ) -> CaseOutcome:
        _check_question(case, question)
        if case.kind is not CaseKind.JUDGE:
            raise ValueError(f"评测题 {case.id} 不是 judge 题")
        judge = self._judge_for(case)
        attempts: list[Attempt] = []
        for _ in range(case.repeats):
            for item in inputs:
                started = self._clock.monotonic()
                judgment = judge.judge(question, item.claims, item.pairs, case.as_of)
                grade = case.grade(judgment.answer, judgment.reasoning)
                if judgment.failure is not None:
                    grade = grade.failing(f"判决调用失败：{judgment.failure.detail}")
                attempt = Attempt(
                    judgment=judgment,
                    as_of=case.as_of,
                    requests=judgment.usage.requests,
                    input_tokens=judgment.usage.input_tokens,
                    output_tokens=judgment.usage.output_tokens,
                    seconds=round(self._clock.monotonic() - started, 2),
                    grade=grade,
                    source=item.source,
                )
                attempts.append(attempt)
                if on_attempt:
                    on_attempt(attempt)
        return CaseOutcome(case=case, attempts=tuple(attempts))
