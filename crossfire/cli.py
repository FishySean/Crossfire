"""命令行入口：uv run crossfire verify|prefetch ...

只做解析参数、把字符串转成领域类型、打印。组装交给 composition，配置交给 config。
"""

import argparse
import sys
import time
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import crossfire.composition as composition
from crossfire.application.records import run_record
from crossfire.config import Settings, SettingsError, load_questions
from crossfire.domain import Mode, Question


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
    return 0


def verify(settings: Settings, targets: Sequence[Question], mode: Mode) -> None:
    started = time.monotonic()
    for question in targets:
        verifier = composition.build_verifier(settings, question, mode)
        try:
            saved = verifier.execute(question)
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


def print_report(result: dict[str, Any], location: str) -> None:
    print("=" * 70)
    print(f"问题：{result['question']}")
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
