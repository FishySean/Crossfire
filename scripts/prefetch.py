#!/usr/bin/env python3
"""把指定问题的所有来源抓一遍存进 out/cache/，给现场演示当降落伞。"""

import argparse
import asyncio
import json
import traceback
from pathlib import Path

import yaml

from crossfire.steel_client import CACHE_ROOT, cache_path, fetch_pages

QUESTIONS_FILE = Path(__file__).resolve().parents[1] / "questions" / "demo.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(description="Crossfire 来源预抓取")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--question", help="按 id 预抓单个问题")
    group.add_argument("--all", action="store_true", help="预抓全部问题")
    args = parser.parse_args()

    questions = yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8"))
    if args.all:
        targets = questions
    else:
        targets = [q for q in questions if q["id"] == args.question]
        if not targets:
            parser.error(f"找不到问题 id: {args.question}。可用：{', '.join(q['id'] for q in questions)}")

    for config in targets:
        print(f"=== {config['id']} ===")
        cache_dir = CACHE_ROOT / config["id"]
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            pages = asyncio.run(fetch_pages([s["url"] for s in config["sources"]]))
        except Exception:
            traceback.print_exc()
            raise

        for page in pages:
            path = cache_path(cache_dir, page["url"])
            path.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
            chars = len(page["markdown"] or "")
            flag = "ok" if page["ok"] else f"失败 {page['error']}"
            print(f"  {flag:<10} {chars:>7} 字符  -> {path.name}  {page['url']}")


if __name__ == "__main__":
    main()
