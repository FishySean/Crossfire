#!/usr/bin/env python3
"""Crossfire 命令行查证入口。"""

import argparse
import time
import traceback
from pathlib import Path

import yaml

from crossfire.pipeline import run

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_FILE = ROOT / "questions" / "demo.yaml"


def load_questions() -> list[dict]:
    return yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8"))


def print_report(result: dict) -> None:
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

    others = [p for p in result["pairs"] if p.get("relation") != "contradict"]
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
    print(f"Claude 调用：{result['claude_calls']} 次")
    print(f"{'步骤':<10}{'调用':>6}{'输入token':>12}{'输出token':>12}{'耗时(s)':>10}")
    for name, step in result["steps"].items():
        print(
            f"{name:<10}{step['calls']:>6}{step.get('input_tokens', 0):>12}"
            f"{step.get('output_tokens', 0):>12}{step['seconds']:>10}"
        )
    print(f"token 合计：输入 {result['total_input_tokens']}，输出 {result['total_output_tokens']}")
    print(f"总耗时：{result['elapsed_seconds']} 秒")
    print(f"完整结果：{result['output_path']}")

    if result["failures"]:
        print(f"\n⚠️  本次有 {len(result['failures'])} 次调用解析失败，结果可能不完整")
        for failure in result["failures"]:
            print(f"  - [{failure['step']}] {failure['detail']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Crossfire 查证引擎")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--question", help="按 id 跑单个问题")
    group.add_argument("--all", action="store_true", help="跑全部问题")
    parser.add_argument(
        "--mode",
        default="live",
        choices=["live", "cached"],
        help="live 走网络抓取，cached 读 out/cache/（Claude 仍真跑）",
    )
    args = parser.parse_args()

    questions = load_questions()

    if args.all:
        targets = questions
    else:
        targets = [q for q in questions if q["id"] == args.question]
        if not targets:
            available = ", ".join(q["id"] for q in questions)
            parser.error(f"找不到问题 id: {args.question}。可用：{available}")

    started = time.monotonic()
    for question_config in targets:
        try:
            print_report(run(question_config, mode=args.mode))
        except Exception:
            traceback.print_exc()
            raise

    if len(targets) > 1:
        print(f"\n全部 {len(targets)} 个问题总耗时：{round(time.monotonic() - started, 2)} 秒")


if __name__ == "__main__":
    main()
