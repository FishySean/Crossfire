"""命令行入口：uv run crossfire verify|prefetch|eval ...

只做解析参数、把字符串转成领域类型、打印。组装交给 composition，配置交给 config。
"""

import argparse
import json
import sys
import time
import traceback
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import crossfire.composition as composition
from crossfire.application.records import run_record
from crossfire.application.use_cases import (
    Attempt,
    BankBuildInterrupted,
    CaseOutcome,
    apply_keep_rules,
    bench_runs,
    cross_model_agreement,
    dataset_readme,
    estimate_bank_build,
    estimate_batch,
    estimate_pair_cost,
    estimate_pair_requests,
    estimate_requests,
    export_pair_dataset,
    label_name,
    remaining_quotas,
    split_question_ids,
)
from crossfire.config import (
    DEFAULT_HAIKU,
    DEFAULT_MODEL,
    MODEL_PRICES,
    STEEL_SCRAPE_PER_THOUSAND_USD,
    WEB_SEARCH_PER_THOUSAND_USD,
    Settings,
    SettingsError,
    load_bank_questions,
    load_consistency_inputs,
    load_eval_cases,
    load_judge_inputs,
    load_questions,
)
from crossfire.domain import (
    BankQuestion,
    DroppedQuestion,
    DropReason,
    Mode,
    ProposedQuestion,
    Question,
    QuestionCategory,
    RunResult,
    UnknownSnapshotDateError,
)
from crossfire.domain.bank import CATEGORY_QUOTAS
from crossfire.domain.evals import CaseKind, EvalCase, JudgeInput


def parse_mode(value: str) -> Mode:
    try:
        return Mode(value)
    except ValueError:
        allowed = "、".join(mode.value for mode in Mode)
        raise argparse.ArgumentTypeError(f"不认识的 mode：{value}，可选：{allowed}") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crossfire", description="Crossfire 查证引擎")
    commands = parser.add_subparsers(dest="command", required=True)

    verify = commands.add_parser("verify", help="查证问题：抓取、提取、比对、下结论")
    _add_targets(verify, "查证")
    verify.add_argument(
        "--mode",
        type=parse_mode,
        default=Mode.LIVE,
        metavar="{live,cached}",
        help="live 走网络抓取，cached 读页面缓存（Claude 仍真跑）。默认 live",
    )

    prefetch = commands.add_parser("prefetch", help="把来源实时抓一遍存进页面缓存，给 cached 模式用")
    _add_targets(prefetch, "预抓")

    evaluate = commands.add_parser("eval", help="跑评测集：只读冻结快照，按标准答案判分")
    evaluate.add_argument("--case", metavar="ID", help="只跑这一道题，默认全部")
    evaluate.add_argument("--estimate-only", action="store_true", help="只打印预计请求数，不跑")

    bench = commands.add_parser("bench", help="汇总评测运行的耗时、token 和估算费用（默认读已有结果，不加跑）")
    bench.add_argument("--case", metavar="ID", help="只看这一道题")
    bench.add_argument("--run", action="store_true", help="先跑一遍评测再汇总（会调模型）")
    bench.add_argument("--estimate-only", action="store_true", help="只打印 --run 时的预计请求数和费用")

    consistency = commands.add_parser("consistency", help="同一批冻结主张反复比对，测标签稳定性")
    consistency.add_argument("--case", metavar="ID", action="append", help="只测这些题，可重复；默认全部")
    consistency.add_argument("--repeats", type=int, default=5, help="每对重复次数，默认 5")
    consistency.add_argument(
        "--models",
        default=f"{DEFAULT_MODEL},{DEFAULT_HAIKU}",
        help=f"逗号分隔的模型列表，默认 {DEFAULT_MODEL},{DEFAULT_HAIKU}",
    )
    consistency.add_argument("--estimate-only", action="store_true", help="只打印预计请求数和费用")

    bank = commands.add_parser("bank", help="题库：自动出题、找来源、抓取过滤")
    bank_commands = bank.add_subparsers(dest="bank_command", required=True)
    build = bank_commands.add_parser("build", help="按类别配额建题库；有进度文件则断点续跑")
    build.add_argument("--estimate-only", action="store_true", help="只打印预计搜索/请求/费用")
    build.add_argument("--fresh", action="store_true", help="忽略进度文件，从头开始")

    batch = commands.add_parser("batch", help="对题库批量跑完整流水线（默认 cached）")
    batch.add_argument("--bank", metavar="PATH", help="题库 YAML，默认 questions/bank.yaml")
    batch.add_argument("--estimate-only", action="store_true", help="只打印预计请求数和费用")
    batch.add_argument("--fresh", action="store_true", help="忽略进度，从头开始")
    batch.add_argument("--budget", type=float, default=12.0, help="Anthropic 预算上限（美元），默认 12")

    dataset = commands.add_parser("dataset", help="训练数据")
    dataset_commands = dataset.add_subparsers(dest="dataset_command", required=True)
    export_cmd = dataset_commands.add_parser("export", help="从批量运行导出 data/pairs.jsonl")
    export_cmd.add_argument("--bank", metavar="PATH", help="题库 YAML，默认 questions/bank.yaml")
    export_cmd.add_argument("--seed", default="crossfire-5c2-2026-11-20", help="按题切分的随机种子")
    return parser


def _add_targets(parser: argparse.ArgumentParser, verb: str) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--question", metavar="ID", help=f"按 id {verb}单个问题")
    group.add_argument("--all", action="store_true", help=f"{verb}全部问题")


def main(argv: Sequence[str] | None = None, settings: Settings | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = settings or Settings.from_env()
    questions = load_questions(settings)

    if args.command == "eval":
        try:
            return evaluate(settings, questions, args.case, args.estimate_only, parser)
        except SettingsError as error:
            print(f"配置不全，没有开始运行：\n{error}", file=sys.stderr)
            return 2

    if args.command == "bench":
        try:
            return bench_command(settings, questions, args.case, args.run, args.estimate_only, parser)
        except SettingsError as error:
            print(f"配置不全，没有开始运行：\n{error}", file=sys.stderr)
            return 2

    if args.command == "consistency":
        try:
            return consistency_command(settings, args.case, args.repeats, args.models, args.estimate_only, parser)
        except SettingsError as error:
            print(f"配置不全，没有开始运行：\n{error}", file=sys.stderr)
            return 2

    if args.command == "bank":
        try:
            return bank_build(settings, args.estimate_only, args.fresh, parser)
        except SettingsError as error:
            print(f"配置不全，没有开始运行：\n{error}", file=sys.stderr)
            return 2

    if args.command == "batch":
        try:
            bank_path = Path(args.bank) if args.bank else settings.bank_file
            return batch_command(settings, bank_path, args.estimate_only, args.fresh, args.budget, parser)
        except SettingsError as error:
            print(f"配置不全，没有开始运行：\n{error}", file=sys.stderr)
            return 2

    if args.command == "dataset":
        try:
            bank_path = Path(args.bank) if getattr(args, "bank", None) else settings.bank_file
            return dataset_export_command(settings, bank_path, args.seed, parser)
        except SettingsError as error:
            print(f"配置不全，没有开始运行：\n{error}", file=sys.stderr)
            return 2

    if args.all:
        targets = questions
    else:
        targets = [q for q in questions if q.id == args.question]
        if not targets:
            available = ", ".join(q.id for q in questions) or f"（{settings.questions_file} 里没有问题）"
            parser.error(f"找不到问题 id: {args.question}。可用：{available}")

    try:
        if args.command == "verify":
            verify(settings, targets, args.mode)
        else:
            prefetch(settings, targets)
    except SettingsError as error:
        print(f"配置不全，没有开始运行：\n{error}", file=sys.stderr)
        return 2
    except UnknownSnapshotDateError as error:
        print(f"没有调用模型就停下了：\n{error}", file=sys.stderr)
        return 2
    return 0


def verify(settings: Settings, targets: Sequence[Question], mode: Mode) -> None:
    from crossfire.config import Pairer

    if settings.pairer is Pairer.NLI:
        # 比对在本地，不计 Anthropic；只估提取 + 判决。
        extracts = sum(len(q.sources) for q in targets)
        judges = len(targets)
        price = settings.price_for(settings.model_extract)
        # 粗估：提取约 4k in / 200 out，判决约 3k in / 400 out（与近期中位数同量级）
        usd = (
            extracts * price.cost_usd(4000, 200)
            + judges * settings.price_for(settings.model_judge).cost_usd(3000, 400)
        )
        print(
            f"PAIRER=nli：比对在本地免费；预计 Claude 调用最多 "
            f"提取 {extracts} + 判决 {judges} = {extracts + judges} 次，约 ${usd:.2f}（不含重试）"
        )
        print(f"NLI 模型：{settings.nli_model}" + (f" @ {settings.nli_model_revision}" if settings.nli_model_revision else ""))

    started = time.monotonic()
    for question in targets:
        verifier = composition.build_verifier(settings, question, mode)
        try:
            saved = verifier.execute(question)
        except UnknownSnapshotDateError:
            raise
        except Exception:
            traceback.print_exc()
            raise
        print_report(run_record(saved.result), saved.location)

    if len(targets) > 1:
        print(f"\n全部 {len(targets)} 个问题总耗时：{round(time.monotonic() - started, 2)} 秒")


def prefetch(settings: Settings, targets: Sequence[Question]) -> None:
    for question in targets:
        print(f"=== {question.id} ===")
        prefetcher = composition.build_prefetcher(settings, question)
        try:
            stored = prefetcher.execute(question)
        except Exception:
            traceback.print_exc()
            raise
        for item in stored:
            page = item.page
            flag = "ok" if page.ok else f"失败 {page.error}"
            print(f"  {flag:<10} {len(page.markdown or ''):>7} 字符  -> {Path(item.location).name}  {page.url}")


def evaluate(
    settings: Settings,
    questions: Sequence[Question],
    case_id: str | None,
    estimate_only: bool,
    parser: argparse.ArgumentParser,
) -> int:
    cases = load_eval_cases(settings)
    if case_id is not None:
        cases = [case for case in cases if case.id == case_id]
        if not cases:
            available = ", ".join(case.id for case in load_eval_cases(settings)) or "（没有评测题）"
            parser.error(f"找不到评测题 {case_id}。可用：{available}")
    by_id = {question.id: question for question in questions}
    missing = sorted({case.question_id for case in cases} - set(by_id))
    if missing:
        parser.error(f"评测题引用的问题不在 {settings.questions_file} 里：{', '.join(missing)}")

    inputs = {case.id: load_judge_inputs(settings, case) for case in cases if case.kind is CaseKind.JUDGE}
    total = 0
    print("预计请求数（上限，不含重试）：")
    for case in cases:
        question = by_id[case.question_id]
        estimate = estimate_requests(case, question, inputs.get(case.id, ()))
        total += estimate
        unit = f"{len(inputs[case.id])} 份判决输入" if case.kind is CaseKind.JUDGE else f"{len(question.sources)} 个来源"
        print(f"  {case.id:<24} {unit} × {case.repeats} 次  最多 {estimate} 次")
    print(f"  合计最多 {total} 次")
    if estimate_only:
        return 0

    outcomes = run_cases(settings, cases, by_id, inputs)
    print_eval_table(outcomes)
    return 0 if all(outcome.passed for outcome in outcomes) else 1


def run_cases(
    settings: Settings,
    cases: Sequence[EvalCase],
    by_id: dict[str, Question],
    inputs: dict[str, list[JudgeInput]],
) -> list[CaseOutcome]:
    full = composition.build_eval_runner(settings)
    judge = composition.build_judge_eval_runner(settings)
    outcomes: list[CaseOutcome] = []
    for case in cases:
        print(f"\n=== {case.id}（{case.kind.value}，as_of {case.as_of}，标准答案 {case.gold_answer}）===")
        question = by_id[case.question_id]
        if case.kind is CaseKind.JUDGE:
            outcomes.append(judge.execute(case, question, inputs[case.id], on_attempt=_print_attempt))
        else:
            outcomes.append(full.execute(case, question, on_attempt=_print_attempt))
    return outcomes


def _print_attempt(attempt: Attempt) -> None:
    flag = "通过" if attempt.grade.passed else "没通过"
    where = attempt.location or f"输入取自 {attempt.source}"
    print(f"  {flag}  {attempt.seconds} 秒  请求 {_count(attempt.requests)}  -> {where}")


def print_eval_table(outcomes: Sequence[CaseOutcome]) -> None:
    print("\n" + "=" * 70)
    print(f"{'题目':<24}{'次':>3}  {'结果':<6}{'置信度':>6}  实际答案 / 没通过的原因")
    requests: list[int | None] = []
    tokens_in = tokens_out = 0
    for outcome in outcomes:
        for number, attempt in enumerate(outcome.attempts, 1):
            judgment = attempt.judgment
            confidence = "n/a" if judgment.confidence is None else f"{judgment.confidence:.2f}"
            flag = "通过" if attempt.grade.passed else "没通过"
            answer = " ".join((judgment.answer or "(没有答案)").split())
            print(f"{outcome.case.id:<24}{number:>3}  {flag:<6}{confidence:>6}  {answer[:90]}")
            for reason in attempt.grade.reasons:
                print(f"{'':<41}✗ {reason}")
            requests.append(attempt.requests)
            tokens_in += attempt.input_tokens
            tokens_out += attempt.output_tokens
    passed = sum(outcome.passed for outcome in outcomes)
    print("-" * 70)
    print(f"通过 {passed}/{len(outcomes)} 道题（每道题所有重复都对才算通过）")
    known = [count for count in requests if count is not None]
    print(f"实际请求 {sum(known)} 次{'（有未记录的）' if len(known) < len(requests) else ''}，token 输入 {tokens_in}，输出 {tokens_out}")


def bench_command(
    settings: Settings,
    questions: Sequence[Question],
    case_id: str | None,
    run: bool,
    estimate_only: bool,
    parser: argparse.ArgumentParser,
) -> int:
    cases = [case for case in load_eval_cases(settings) if case.kind is CaseKind.FULL]
    if case_id is not None:
        cases = [case for case in cases if case.id == case_id]
        if not cases:
            parser.error(f"找不到 full 评测题 {case_id}")
    by_id = {question.id: question for question in questions}

    if run or estimate_only:
        total = sum(estimate_requests(case, by_id[case.question_id]) for case in cases)
        # 用最近一次同类运行的平均 token 估费用；没有历史就按每请求 3000/250 估。
        avg_in, avg_out = _avg_tokens_from_eval_runs(settings, cases) or (3000, 250)
        price = settings.price_for(settings.model_extract)
        cost = price.cost_usd(total * avg_in, total * avg_out)
        print(f"预计请求数（上限，不含重试）：最多 {total} 次")
        print(f"预计费用（按 {settings.model_extract}，约 {avg_in}/{avg_out} token/请求）：约 ${cost:.2f}")
        if estimate_only:
            return 0
        outcomes = run_cases(settings, cases, by_id, {})
        print_eval_table(outcomes)
        if not all(outcome.passed for outcome in outcomes):
            return 1

    labeled = _latest_full_runs(settings, [case.id for case in cases])
    if not labeled:
        print("没有可汇总的评测运行。先 uv run crossfire eval，或加 --run。", file=sys.stderr)
        return 1
    prices = {model: settings.price_for(model) for model in {DEFAULT_MODEL, settings.model_extract, settings.model_pair, settings.model_judge}}
    # 把运行里出现过的模型也登记上，查不到单价就在 price_for 时报错。
    for _, _, result in labeled:
        for item in (result.provenance or {}).values():
            prices[item.model] = settings.price_for(item.model)
    report = bench_runs(labeled, prices, settings.model_extract)
    print_bench_table(report)
    return 0


def consistency_command(
    settings: Settings,
    case_ids: list[str] | None,
    repeats: int,
    models_arg: str,
    estimate_only: bool,
    parser: argparse.ArgumentParser,
) -> int:
    if repeats < 1:
        parser.error("--repeats 必须是正整数")
    models = [name.strip() for name in models_arg.split(",") if name.strip()]
    if not models:
        parser.error("--models 不能为空")
    inputs = load_consistency_inputs(settings, case_ids)
    if not inputs:
        print(f"没有稳定性输入（{settings.evals_dir / 'consistency_inputs'}）。", file=sys.stderr)
        return 1
    prices = {model: settings.price_for(model) for model in models}
    avg_in, avg_out = 2700, 220
    requests = estimate_pair_requests(inputs, repeats, models)
    cost = estimate_pair_cost(inputs, repeats, models, prices, avg_input=avg_in, avg_output=avg_out)
    print("预计请求数（上限，不含重试）：")
    for item in inputs:
        pairs = len(item.claims) * (len(item.claims) - 1) // 2
        print(f"  {item.case_id:<24} {len(item.claims)} 条主张 → {pairs} 对 × {repeats} 次 × {len(models)} 个模型")
    print(f"  合计最多 {requests} 次")
    print(f"预计费用（按约 {avg_in}/{avg_out} token/次）：约 ${cost:.2f}")
    print(f"  模型：{', '.join(f'{m} (${prices[m].input_per_mtok}/${prices[m].output_per_mtok} per MTok)' for m in models)}")
    if estimate_only:
        return 0

    runner = composition.build_consistency_runner(settings)
    results = runner.execute(inputs, models, repeats, prices)
    location = _save_consistency(settings, inputs, models, repeats, results)
    print_consistency_report(results, models)
    print(f"完整结果：{location}")
    return 0


def print_bench_table(report) -> None:
    print("\n" + "=" * 78)
    print(f"{'步骤':<10}{'调用':>8}{'请求':>8}{'输入token':>12}{'输出token':>12}{'耗时(s)':>10}{'费用($)':>10}")
    for step in report.totals_by_step():
        print(
            f"{step.name:<10}{step.calls:>8}{_count(step.requests):>8}{step.input_tokens:>12}"
            f"{step.output_tokens:>12}{step.seconds:>10.2f}{step.cost_usd:>10.3f}"
        )
    print("-" * 78)
    print(f"合计耗时 {report.total_seconds:.2f} 秒，估算费用 ${report.total_cost_usd:.3f}（{len(report.runs)} 次运行）")
    slowest = report.slowest_step()
    costliest = report.costliest_step()
    if slowest and costliest:
        print(f"最慢的是 {slowest.name}（{slowest.seconds:.2f} 秒），最贵的是 {costliest.name}（${costliest.cost_usd:.3f}）。")


def print_consistency_report(results: dict, models: Sequence[str]) -> None:
    print("\n" + "=" * 78)
    for model in models:
        result = results[model]
        print(f"\n### {model}")
        print(f"整体一致率（跟多数票一致的判断占比）：{result.overall_agreement:.1%}")
        print(f"请求 {result.requests} 次，token 输入 {result.input_tokens}，输出 {result.output_tokens}，费用 ${result.cost_usd:.3f}")
        confusion = result.confusion().most_common(5)
        if confusion:
            print("混淆最多的类别对（多数票 → 少数票）：")
            for (majority, other), count in confusion:
                print(f"  {majority} → {other}：{count} 次")
        else:
            print("全部配对 5 票一致。")
        disputed = [pair for pair in result.pairs if not pair.unanimous]
        print(f"不是全票一致的配对：{len(disputed)} / {len(result.pairs)}")
        for pair in disputed:
            votes = ", ".join(label_name(trial.relation) for trial in pair.trials)
            print(f"\n  [{pair.case_id}] 多数票 {label_name(pair.majority)}（{pair.majority_count}/{len(pair.trials)}）  各次：{votes}")
            print(f"  A: {pair.a_claim[:120]}")
            print(f"     {pair.a_url}")
            print(f"  B: {pair.b_claim[:120]}")
            print(f"     {pair.b_url}")

    if len(models) >= 2:
        reference = results[models[0]]
        print("\n### 跨模型多数票一致率")
        for model in models[1:]:
            rate = cross_model_agreement(reference, results[model])
            print(f"  {models[0]} vs {model}：{rate:.1%}")
            if rate >= 0.9:
                print(f"  建议：比对可以换成 {model}，多数票几乎一致，费用更低。")
            elif rate >= 0.8:
                print(f"  建议：{model} 可作候选，但先人工看不一致的配对再决定。")
            else:
                print(f"  建议：先别换 {model}，跟 {models[0]} 差得还多。")


def _latest_full_runs(settings: Settings, case_ids: Sequence[str]) -> list[tuple[str, str, RunResult]]:
    labeled: list[tuple[str, str, RunResult]] = []
    for case_id in case_ids:
        directory = settings.eval_runs_dir / case_id
        if not directory.is_dir():
            continue
        files = sorted(directory.glob("*.json"))
        if not files:
            continue
        path = files[-1]
        labeled.append((case_id, str(path), RunResult.from_dict(json.loads(path.read_text(encoding="utf-8")))))
    return labeled


def _avg_tokens_from_eval_runs(settings: Settings, cases: Sequence[EvalCase]) -> tuple[int, int] | None:
    ins: list[int] = []
    outs: list[int] = []
    for case_id, _, result in _latest_full_runs(settings, [case.id for case in cases]):
        for record in [*result.claims, *result.pairs, result.judgment]:
            if record.usage.requests:
                ins.append(record.usage.input_tokens)
                outs.append(record.usage.output_tokens)
    if not ins:
        return None
    return round(sum(ins) / len(ins)), round(sum(outs) / len(outs))


def _save_consistency(settings: Settings, inputs, models, repeats, results) -> Path:
    settings.consistency_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = settings.consistency_dir / f"consistency_{stamp}.json"
    payload = {
        "repeats": repeats,
        "models": list(models),
        "inputs": [{"case_id": item.case_id, "source": item.source, "claims": len(item.claims)} for item in inputs],
        "results": {
            model: {
                "overall_agreement": result.overall_agreement,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "requests": result.requests,
                "cost_usd": result.cost_usd,
                "confusion": [{"majority": a, "other": b, "count": n} for (a, b), n in result.confusion().most_common()],
                "pairs": [
                    {
                        "case_id": pair.case_id,
                        "a_url": pair.a_url,
                        "b_url": pair.b_url,
                        "a_claim": pair.a_claim,
                        "b_claim": pair.b_claim,
                        "majority": label_name(pair.majority),
                        "majority_count": pair.majority_count,
                        "votes": [label_name(trial.relation) for trial in pair.trials],
                        "natures": [trial.nature for trial in pair.trials],
                    }
                    for pair in result.pairs
                ],
            }
            for model, result in results.items()
        },
    }
    if len(models) >= 2:
        payload["cross_model"] = {
            model: cross_model_agreement(results[models[0]], results[model]) for model in models[1:]
        }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def bank_build(settings: Settings, estimate_only: bool, fresh: bool, parser: argparse.ArgumentParser) -> int:
    import yaml

    as_of = composition.utc_today()
    kept_prev, dropped_prev = ([], []) if fresh else _load_bank_progress(settings)
    # 续跑前先按现行规则筛一遍，算出还能复用多少、要重做多少。
    reusable: list[BankQuestion] = []
    demoted: list[DroppedQuestion] = []
    by_cat: dict[QuestionCategory, int] = {category: 0 for category in CATEGORY_QUOTAS}
    for question in kept_prev:
        failure = apply_keep_rules(question)
        if failure is not None:
            demoted.append(failure)
            continue
        if by_cat[question.category] >= CATEGORY_QUOTAS[question.category]:
            demoted.append(
                DroppedQuestion(
                    proposed=ProposedQuestion(
                        id=question.id,
                        text=question.text,
                        category=question.category,
                        language=question.language,
                        keywords=question.keywords,
                    ),
                    reason=DropReason.TOO_FEW_USABLE,
                    detail=f"{question.category.value} 已满配额 {CATEGORY_QUOTAS[question.category]}，多出来的不保留",
                    rejected=question.rejected,
                )
            )
            continue
        by_cat[question.category] += 1
        reusable.append(question)
    interrupted = [item.proposed for item in dropped_prev if item.reason is DropReason.INTERRUPTED]
    need = remaining_quotas(reusable)
    propose_n = sum(need.values())
    price = settings.price_for(settings.model_extract)
    estimate = estimate_bank_build(
        redo=len(interrupted),
        propose=propose_n,
        searches_per_question=6,
        candidates_per_question=8,
        search_per_thousand_usd=WEB_SEARCH_PER_THOUSAND_USD,
        sonnet_input_per_mtok=price.input_per_mtok,
        sonnet_output_per_mtok=price.output_per_mtok,
        steel_per_scrape_usd=STEEL_SCRAPE_PER_THOUSAND_USD / 1000,
        reuse=len(reusable),
    )
    print("续跑计划：")
    print(f"  复用已成功 {len(reusable)} 道（另有 {len(demoted)} 道因新规则/超额降级）")
    print(f"  重做中断 {len(interrupted)} 道：{[p.id for p in interrupted]}")
    print(f"  配额缺口 {dict((c.value, n) for c, n in need.items() if n)} → 预计新出约 {propose_n} 道")
    print(f"  合计新做最多 {estimate.redo} 道题")
    print("预计费用（只计新做，偏高）：")
    print(f"  Claude 请求最多 {estimate.claude_requests} 次，web_search 最多 {estimate.searches} 次")
    print(f"  Anthropic 约 ${estimate.total_anthropic_usd:.2f}（token ${estimate.anthropic_usd:.2f} + 搜索 ${estimate.search_usd:.2f}）")
    print(f"  Steel 抓取最多 {estimate.steel_pages} 页（scrape 约 ${estimate.steel_usd:.2f}）")
    if estimate.total_anthropic_usd > 3:
        print(
            f"Anthropic 预计 ${estimate.total_anthropic_usd:.2f}，超过 3 美元上限，没有开始运行。",
            file=sys.stderr,
        )
        return 2
    if estimate_only:
        return 0

    def save_progress(kept: list, dropped: list) -> None:
        _write_bank_progress(settings, as_of, kept, dropped)
        _write_bank_yaml(settings.bank_file, kept)

    avoid = tuple({q.id for q in reusable} | {d.proposed.id for d in demoted} | {d.proposed.id for d in dropped_prev})
    builder = composition.build_question_bank_builder(settings, avoid_ids=avoid, on_progress=save_progress)
    print(f"开始生成题库（as_of {as_of}）…")
    try:
        kept, dropped = builder.execute(
            as_of,
            kept=reusable,
            dropped=[*demoted, *[d for d in dropped_prev if d.reason is not DropReason.INTERRUPTED]],
            retry=interrupted,
        )
    except BankBuildInterrupted as error:
        print(f"余额不足或鉴权失败，立刻停下（当前题 {error.question_id}）：{error.detail}", file=sys.stderr)
        return 2

    save_progress(kept, dropped)
    _write_bank_review(settings.bank_review_file, kept, dropped, as_of)
    print(f"保留 {len(kept)} 道，丢弃 {len(dropped)} 道")
    shortfall = remaining_quotas(kept)
    if sum(shortfall.values()):
        print(f"未凑满配额：{dict((c.value, n) for c, n in shortfall.items() if n)}")
    else:
        print(f"配额已满：{ {c.value: n for c, n in CATEGORY_QUOTAS.items()} }")
    print(f"题库：{settings.bank_file}")
    print(f"进度：{settings.bank_progress_file}")
    print(f"审查报告：{settings.bank_review_file}")
    print("请先看 notes/bank-review.md，确认后再进入 5c-2。")
    return 0


def _load_bank_progress(settings: Settings) -> tuple[list[BankQuestion], list[DroppedQuestion]]:
    import yaml

    path = settings.bank_progress_file
    if not path.is_file():
        # 兼容第一次中断留下的 bank.yaml：没有进度文件时从题库恢复 kept。
        if settings.bank_file.is_file():
            raw = yaml.safe_load(settings.bank_file.read_text(encoding="utf-8")) or []
            return [BankQuestion.from_yaml_dict(item) for item in raw], []
        return [], []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    kept = [BankQuestion.from_yaml_dict(item) for item in data.get("kept") or []]
    dropped = [DroppedQuestion.from_dict(item) for item in data.get("dropped") or []]
    return kept, dropped


def _write_bank_progress(settings: Settings, as_of, kept: Sequence, dropped: Sequence) -> None:
    import yaml

    path = settings.bank_progress_file
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "as_of": as_of.isoformat(),
        "kept": [question.to_yaml_dict() for question in kept],
        "dropped": [item.to_dict() for item in dropped],
    }
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _write_bank_yaml(path: Path, kept: Sequence) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [question.to_yaml_dict() for question in kept]
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _write_bank_review(path: Path, kept: Sequence, dropped: Sequence, as_of) -> None:
    from collections import Counter

    path.parent.mkdir(parents=True, exist_ok=True)
    shortfall = remaining_quotas(kept)
    lines = [
        "# 题库审查报告",
        "",
        f"生成日期（as_of）：{as_of.isoformat()}",
        f"保留 {len(kept)} 道，丢弃 {len(dropped)} 道。",
        f"类别配额：{ {c.value: n for c, n in CATEGORY_QUOTAS.items()} }",
        f"未凑满：{ {c.value: n for c, n in shortfall.items() if n} or '无' }",
        "",
        "## 保留的题目",
        "",
        "| id | 题目 | 类别 | 语言 | 可用 | primary | news | aggregator |",
        "|---|---|---|---|---:|---:|---:|---:|",
    ]
    for question in kept:
        tiers = Counter(item.source.tier.value for item in question.sources)
        text = question.text.replace("|", "\\|")
        lines.append(
            f"| {question.id} | {text} | {question.category.value} | {question.language} | "
            f"{len(question.sources)} | {tiers['primary']} | {tiers['news']} | {tiers['aggregator']} |"
        )
    lines += ["", "## 丢弃的题目", ""]
    if not dropped:
        lines.append("（没有）")
    else:
        lines.append("| id | 题目 | 类别 | 原因 | 说明 |")
        lines.append("|---|---|---|---|---|")
        for item in dropped:
            text = item.proposed.text.replace("|", "\\|")
            lines.append(
                f"| {item.proposed.id} | {text} | {item.proposed.category.value} | "
                f"{item.reason.value} | {item.detail.replace('|', '\\|')} |"
            )

    by_category = Counter(q.category.value for q in kept)
    by_language = Counter(q.language for q in kept)
    reject_reasons = Counter(r.reason.value for q in kept for r in q.rejected)
    reject_reasons.update(r.reason.value for d in dropped for r in d.rejected)
    drop_reasons = Counter(d.reason.value for d in dropped)
    total_rejected = sum(reject_reasons.values())
    total_considered = total_rejected + sum(len(q.sources) for q in kept)
    filter_line = (
        f"- 被过滤的页面：{total_rejected} / {total_considered}（{total_rejected / total_considered:.0%}）"
        if total_considered
        else "- 被过滤的页面：0"
    )
    lines += [
        "",
        "## 统计",
        "",
        f"- 按类别：{dict(by_category)}",
        f"- 按语言：{dict(by_language)}",
        filter_line,
        f"- 过滤原因：{dict(reject_reasons)}",
        f"- 丢题原因：{dict(drop_reasons)}",
        "",
        "请确认：题目有确定答案、不是公认争议话题；来源层级有混搭；每题至少 1 个 primary；过滤比例可接受。",
        "确认后再进入 5c-2。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def batch_command(
    settings: Settings,
    bank_path: Path,
    estimate_only: bool,
    fresh: bool,
    budget: float,
    parser: argparse.ArgumentParser,
) -> int:
    import yaml

    from crossfire.application.use_cases import RunBatch

    bank = load_bank_questions(settings, bank_path)
    # design_note 不得进流水线：to_pipeline_question 已剥离；这里再扫一遍正文。
    for question in bank:
        if question.design_note and question.design_note in question.text:
            parser.error(f"{question.id}: design_note 写进了题目正文")

    done: list[str] = []
    if not fresh and settings.batch_progress_file.is_file():
        progress = yaml.safe_load(settings.batch_progress_file.read_text(encoding="utf-8")) or {}
        done = [str(item) for item in progress.get("done") or []]
    pending = [question for question in bank if question.id not in set(done)]
    estimate = estimate_batch(pending, price=settings.price_for(settings.model_extract))
    print("批量运行计划：")
    print(f"  题库 {bank_path}：共 {len(bank)} 道，已完成 {len(done)}，待跑 {len(pending)}")
    print(f"  预计请求：提取 {estimate.extracts} + 比对 {estimate.pairs} + 判决 {estimate.judges} = {estimate.requests}")
    print(f"  预计 Anthropic 约 ${estimate.anthropic_usd:.2f}（按近期中位 token）")
    if estimate.anthropic_usd > budget:
        print(
            f"预计 ${estimate.anthropic_usd:.2f} 超过预算上限 ${budget:.2f}，没有开始运行。",
            file=sys.stderr,
        )
        return 2
    if estimate_only or not pending:
        if not pending:
            print("没有待跑的题目。")
        return 0

    settings.batch_dir.mkdir(parents=True, exist_ok=True)

    def save_progress(ids: list[str]) -> None:
        settings.batch_progress_file.parent.mkdir(parents=True, exist_ok=True)
        settings.batch_progress_file.write_text(
            yaml.safe_dump({"done": ids, "bank": str(bank_path)}, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def on_saved(question, saved) -> None:
        # 额外按题号存一份，方便 dataset export / consistency 取用。
        target = settings.batch_dir / f"{question.id}.json"
        target.write_text(
            json.dumps(run_record(saved.result), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"  ✓ {question.id} → {saved.location}（副本 {target.name}）")

    runner = RunBatch(
        verifier_for=lambda question: composition.build_verifier(settings, question, Mode.CACHED),
        on_progress=save_progress,
        on_saved=on_saved,
    )
    print(f"开始批量运行（cached，预算 ${budget:.2f}）…")
    try:
        results = runner.execute(pending, done_ids=done)
    except Exception as error:
        detail = str(error).lower()
        if any(token in detail for token in ("credit balance", "insufficient", "authentication", "401", "403", "402")):
            print(f"余额不足或鉴权失败，立刻停下：{error}", file=sys.stderr)
            return 2
        raise
    print(f"本轮完成 {len(results)} 道。进度：{settings.batch_progress_file}")
    return 0


def dataset_export_command(settings: Settings, bank_path: Path, seed: str, parser: argparse.ArgumentParser) -> int:
    from crossfire.domain import RunResult

    bank = load_bank_questions(settings, bank_path)
    runs: dict[str, RunResult] = {}
    for question in bank:
        path = settings.batch_dir / f"{question.id}.json"
        if not path.is_file():
            parser.error(f"缺少批量结果 {path}，先跑 crossfire batch")
        runs[question.id] = RunResult.from_dict(json.loads(path.read_text(encoding="utf-8")))

    sonnet_consistency = _load_batch_consistency(settings, settings.model_pair)
    export = export_pair_dataset(
        bank,
        runs,
        sonnet_consistency=sonnet_consistency,
        split=split_question_ids([question.id for question in bank], seed=seed),
        seed=seed,
        pair_model=settings.model_pair,
    )
    settings.dataset_dir.mkdir(parents=True, exist_ok=True)
    pairs_path = settings.dataset_dir / "pairs.jsonl"
    with pairs_path.open("w", encoding="utf-8") as handle:
        for example in export.examples:
            handle.write(json.dumps(example.to_jsonl_dict(), ensure_ascii=False) + "\n")
    readme = dataset_readme(export)
    (settings.dataset_dir / "README.md").write_text(readme, encoding="utf-8")
    print(readme)
    print(f"已写入 {pairs_path}（{len(export.examples)} 条）")
    return 0


def _load_batch_consistency(settings: Settings, model: str):
    """若存在 out/consistency/batch-5c2.json，读出该模型的 ModelConsistency。"""
    path = settings.consistency_dir / "batch-5c2.json"
    if not path.is_file():
        return None
    from crossfire.application.use_cases.measure_consistency import ModelConsistency, PairSummary, PairTrial
    from crossfire.domain import Relation

    def parse_relation(value: object) -> Relation | None:
        if value is None or value == "None" or value == "":
            return None
        return Relation(str(value))

    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("results", {}).get(model)
    if not raw:
        return None
    pairs = []
    for item in raw["pairs"]:
        if "trials" in item:
            trials = tuple(
                PairTrial(relation=parse_relation(trial.get("relation")), nature=trial.get("nature"))
                for trial in item["trials"]
            )
        else:
            votes = item.get("votes") or []
            natures = item.get("natures") or [None] * len(votes)
            trials = tuple(
                PairTrial(relation=parse_relation(vote), nature=nature)
                for vote, nature in zip(votes, natures, strict=True)
            )
        pairs.append(
            PairSummary(
                case_id=item["case_id"],
                a_url=item["a_url"],
                b_url=item["b_url"],
                a_claim=item["a_claim"],
                b_claim=item["b_claim"],
                trials=trials,
                majority=parse_relation(item.get("majority")),
                majority_count=int(item["majority_count"]),
            )
        )
    return ModelConsistency(
        model=model,
        pairs=tuple(pairs),
        input_tokens=int(raw.get("input_tokens") or 0),
        output_tokens=int(raw.get("output_tokens") or 0),
        requests=int(raw.get("requests") or 0),
        cost_usd=float(raw.get("cost_usd") or 0),
    )


def write_consistency_inputs_from_batch(settings: Settings, case_ids: Sequence[str]) -> list[Path]:
    """从批量结果抽出冻结主张，写成 consistency 可读的输入文件。"""
    from crossfire.domain import RunResult

    out_dir = settings.consistency_dir / "inputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for case_id in case_ids:
        run_path = settings.batch_dir / f"{case_id}.json"
        if not run_path.is_file():
            raise SettingsError(f"写稳定性输入失败：缺少 {run_path}")
        result = RunResult.from_dict(json.loads(run_path.read_text(encoding="utf-8")))
        claims = [claim for claim in result.claims if claim.answered]
        if len(claims) < 2:
            print(f"跳过 {case_id}：可比对主张不足 2 条", file=sys.stderr)
            continue
        payload = {
            "case_id": case_id,
            "question_id": result.question.id,
            "question": result.question.text,
            "as_of": None if result.as_of is None else result.as_of.isoformat(),
            "source_run": str(run_path),
            "claims": [claim.to_dict() for claim in claims],
        }
        path = out_dir / f"{case_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written


def print_report(result: dict[str, Any], location: str) -> None:
    print("=" * 70)
    print(f"问题：{result['question']}")
    print(f"告诉模型的今天：{result['as_of']}    模式：{result['mode']}")
    print("=" * 70)

    print("\n--- 各来源主张 ---")
    for claim in result["claims"]:
        text = claim.get("claim") or "(该页面没有回答这个问题)"
        date = claim.get("published_date") or "日期未知"
        confidence = claim.get("confidence")
        confidence = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "n/a"
        print(f"[{claim.get('tier')}] {claim['url']}")
        print(f"    主张：{text}")
        print(f"    依据：{claim.get('evidence') or '-'}")
        print(f"    日期：{date}    置信度：{confidence}    类型：{claim.get('source_type')}")
        if claim.get("failure"):
            print(f"    调用失败：{claim['failure']['detail']}")

    for page in result["pages"]:
        if not page["ok"]:
            print(f"[抓取失败] {page['url']}  status={page['status_code']}")
            print(f"    {page['error']}")

    print("\n--- 来源两两比对 ---")
    contradictions = [p for p in result["pairs"] if p.get("relation") == "contradict"]
    if contradictions:
        for pair in contradictions:
            print(f">>> [矛盾] {pair['nature']}")
            print(f"      A: {pair['a']}")
            print(f"      B: {pair['b']}")
    else:
        print("未发现相互矛盾的来源。")

    scoped = [p for p in result["pairs"] if p.get("relation") == "same_question_different_scope"]
    for pair in scoped:
        print(f"  ~~~ [口径不同] {pair['nature']}")
        print(f"      A: {pair['a']}")
        print(f"      B: {pair['b']}")

    others = [p for p in result["pairs"] if p.get("relation") not in ("contradict", "same_question_different_scope")]
    for pair in others:
        print(f"    [{pair.get('relation')}] {pair.get('nature')}")
        print(f"      {pair['a']}")
        print(f"      {pair['b']}")

    judgment = result["judgment"]
    print("\n--- 结论 ---")
    print(f"回答：{judgment.get('answer')}")
    confidence = judgment.get("confidence")
    print(f"置信度：{confidence:.2f}" if isinstance(confidence, (int, float)) else "置信度：n/a")
    print(f"推理：{judgment.get('reasoning')}")
    if judgment.get("conflicts"):
        print("分歧：")
        for conflict in judgment["conflicts"]:
            print(f"  - {conflict}")
    if judgment.get("trusted_sources"):
        print("采信来源（可信度降序）：")
        for url in judgment["trusted_sources"]:
            print(f"  - {url}")
    if judgment.get("failure"):
        print(f"调用失败：{judgment['failure']['detail']}")

    print("\n--- 本次消耗 ---")
    print(f"抓取页面：{result['pages_fetched']} 成功 / {result['pages_failed']} 失败")
    print(f"模型请求：{_count(result['claude_calls'])} 次（含重试）")
    print(f"{'步骤':<10}{'调用':>6}{'请求':>6}{'输入token':>12}{'输出token':>12}{'耗时(s)':>10}")
    for name, step in result["steps"].items():
        print(
            f"{name:<10}{step['calls']:>6}{_count(step.get('requests', '-')):>6}{step.get('input_tokens', 0):>12}"
            f"{step.get('output_tokens', 0):>12}{step['seconds']:>10}"
        )
    print(f"token 合计：输入 {result['total_input_tokens']}，输出 {result['total_output_tokens']}")
    for step, item in (result["provenance"] or {}).items():
        print(f"{step:<10}模型 {item['model']}  prompt {item['prompt_version'] or '-'}")
    print(f"总耗时：{result['elapsed_seconds']} 秒")
    print(f"完整结果：{location}")

    if result["failures"]:
        print(f"\n⚠️  本次有 {len(result['failures'])} 处失败，结果可能不完整")
        for failure in result["failures"]:
            print(f"  - [{failure['step']}] {failure['detail']}")


def _count(value: object) -> str:
    return "未记录" if value is None else str(value)


if __name__ == "__main__":
    sys.exit(main())
