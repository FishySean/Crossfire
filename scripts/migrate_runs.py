#!/usr/bin/env python3
"""把 out/runs/ 下的旧结果文件迁到当前格式，让每个文件都能被 RunResult.from_dict 读回来。

默认只演练（dry-run）：列出每个文件要改什么，一个字节都不写。加 --apply 才写：
先把整个目录原样备份到 runs.bak-<时间戳>/，再逐个原子替换要改的文件。可以重复跑，改过的不会再改。

改三类问题：
  - 早期文件没有 mode 键：那时只有实时抓取，补 "mode": "live"。
  - 开始统计请求数之前的 usage 和步骤统计没有 requests 键：补 null，表示「当时没有记录」，
    不是 0。这样的文件顶层 claude_calls 也改成 null：旧值没算重试，和逐条记录对不上。
  - 模型把 judgment.conflicts 整个数组编码成了一个 JSON 字符串：解析回数组。字符串里的引号没转义、
    json.loads 解析不了时，按 ["…", "…"] 的外形在 ", " 处切开，演练输出里列出切出来的每一条供人核对。
"""

import argparse
import copy
import json
import os
import shutil
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crossfire.config import Settings
from crossfire.domain import RunResult


def migrate(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """返回 (迁移后的副本, 改动说明)。已经是当前格式时改动说明为空，副本与原件相等。"""
    data = copy.deepcopy(data)
    changes: list[str] = []

    if "mode" not in data:
        data = _insert_after(data, "question", "mode", "live")
        changes.append("补 mode=live")

    records = [*data.get("claims", []), *data.get("pairs", []), data.get("judgment") or {}]
    usages = [r["usage"] for r in records if isinstance(r.get("usage"), dict) and "requests" not in r["usage"]]
    for usage in usages:
        usage["requests"] = None
    if usages:
        changes.append(f"{len(usages)} 条记录的 usage 补 requests=null")

    steps = [name for name, step in data.get("steps", {}).items() if "input_tokens" in step and "requests" not in step]
    for name in steps:
        data["steps"][name]["requests"] = None
    if steps:
        changes.append(f"步骤 {'、'.join(steps)} 补 requests=null")

    if (usages or steps) and data.get("claude_calls") is not None:
        changes.append(f"claude_calls {data['claude_calls']} → null")
        data["claude_calls"] = None

    judgment = data.get("judgment") or {}
    conflicts = judgment.get("conflicts")
    if isinstance(conflicts, str):
        parsed, how = _parse_string_list(conflicts)
        judgment["conflicts"] = parsed
        changes.append(f"judgment.conflicts 字符串 → 数组（{len(parsed)} 条，{how}）")
        changes.extend(f"    [{i}] {item[:40]}…" for i, item in enumerate(parsed))

    return data, changes


def _parse_string_list(text: str) -> tuple[list[str], str]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        stripped = text.strip()
        if not (stripped.startswith('["') and stripped.endswith('"]')):
            raise ValueError("judgment.conflicts 是字符串，既不是合法 JSON，也不是 [\"…\", \"…\"] 的外形") from None
        items = stripped[2:-2].split('", "')
        if not all(item.strip() for item in items):
            raise ValueError("judgment.conflicts 按 \", \" 切开后有空条目，不敢猜") from None
        return items, "JSON 不合法（引号没转义），按 \", \" 切开"
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ValueError("judgment.conflicts 是字符串，但解析出来不是字符串数组")
    return [str(item) for item in parsed], "json.loads 解析"


def _insert_after(data: dict[str, Any], anchor: str, key: str, value: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for existing, existing_value in data.items():
        result[existing] = existing_value
        if existing == anchor:
            result[key] = value
    result.setdefault(key, value)
    return result


def plan(runs_dir: Path) -> tuple[list[tuple[Path, dict[str, Any], list[str]]], list[str]]:
    """返回 (要改的文件, 问题)。问题是迁移不了或迁移后仍读不回来的文件，这些文件不会被写。"""
    todo: list[tuple[Path, dict[str, Any], list[str]]] = []
    problems: list[str] = []
    for path in sorted(runs_dir.glob("*.json")):
        try:
            migrated, changes = migrate(json.loads(path.read_text(encoding="utf-8")))
            RunResult.from_dict(migrated)
        except Exception as error:
            problems.append(f"{path.name}: {type(error).__name__}: {error}")
            continue
        if changes:
            todo.append((path, migrated, changes))
    return todo, problems


def main(argv: Sequence[str] | None = None, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(description="把旧结果文件迁到当前格式（默认只演练）")
    parser.add_argument("--apply", action="store_true", help="真的写文件（先整目录备份）")
    args = parser.parse_args(argv)
    runs_dir = (settings or Settings.from_env()).runs_dir

    files = sorted(runs_dir.glob("*.json"))
    todo, problems = plan(runs_dir)
    print(f"{runs_dir}：{len(files)} 个结果文件，{len(todo)} 个要改，{len(problems)} 个有问题")
    for path, _, changes in todo:
        print(f"  改  {path.name}")
        for change in changes:
            print(f"        - {change}")
    for problem in problems:
        print(f"  ✗   {problem}")

    if not args.apply:
        print("演练模式，没有写任何文件。确认无误后加 --apply。")
        return 1 if problems else 0
    if not todo:
        print("没有要改的文件，不备份也不写。")
        return 1 if problems else 0

    backup = runs_dir.parent / f"{runs_dir.name}.bak-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    shutil.copytree(runs_dir, backup)
    print(f"已备份整个目录到 {backup}")
    for path, migrated, _ in todo:
        staging = path.with_suffix(".json.tmp")
        staging.write_text(json.dumps(migrated, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(staging, path)
    print(f"已写入 {len(todo)} 个文件。")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
