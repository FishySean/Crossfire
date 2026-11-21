"""清掉仓库里 *.ipynb 的执行输出，再提交。用法：uv run python scripts/strip_notebook_outputs.py"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def strip_file(path: Path) -> bool:
    nb = json.loads(path.read_text(encoding="utf-8"))
    changed = False
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        if cell.get("outputs"):
            cell["outputs"] = []
            changed = True
        if cell.get("execution_count") not in (None,):
            cell["execution_count"] = None
            changed = True
    if changed:
        path.write_text(json.dumps(nb, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    paths = sorted(ROOT.joinpath("training").glob("*.ipynb"))
    touched = [str(path.relative_to(ROOT)) for path in paths if strip_file(path)]
    if touched:
        print("cleared outputs:", *touched, sep="\n  ")
    else:
        print("already clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
