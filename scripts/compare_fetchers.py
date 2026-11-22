"""用 HttpPageFetcher 重抓 out/cache 里 Steel 存过的 URL，对比可用率（不调 Claude）。

用法：
  uv run python scripts/compare_fetchers.py
  uv run python scripts/compare_fetchers.py --limit 40
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from crossfire.composition import build_live_fetcher
from crossfire.config import ROOT, Fetcher, Settings
from crossfire.domain import Page
from crossfire.domain.usability import is_usable_page

CACHE_ROOT = ROOT / "out" / "cache"


def _urls_from_cache(cache_root: Path) -> list[tuple[str, Page]]:
    rows: list[tuple[str, Page]] = []
    seen: set[str] = set()
    for path in sorted(cache_root.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or "url" not in data:
            continue
        page = Page.from_dict(data)
        if page.url in seen:
            continue
        seen.add(page.url)
        rows.append((page.url, page))
    return rows


def _short_reason(error: str | None) -> str:
    if not error:
        return "unknown"
    if "HTTP 403" in error or "403" in error:
        return "http_403"
    if "HTTP 429" in error or "429" in error:
        return "http_429"
    if "不支持的内容类型" in error:
        return "non_html"
    if "大小上限" in error:
        return "too_large"
    if "Timeout" in error or "timeout" in error.casefold():
        return "timeout"
    if re.search(r"HTTP 4\d\d", error):
        return "http_4xx"
    if re.search(r"HTTP 5\d\d", error):
        return "http_5xx"
    return "other"


def main() -> int:
    parser = argparse.ArgumentParser(description="对比 Steel 缓存与 HttpPageFetcher")
    parser.add_argument("--cache", type=Path, default=CACHE_ROOT)
    parser.add_argument("--limit", type=int, default=0, help="最多对比多少个 URL，0=全部")
    args = parser.parse_args()

    rows = _urls_from_cache(args.cache)
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print(f"没有缓存页面：{args.cache}")
        return 1

    urls = [url for url, _ in rows]
    print(f"对比 {len(urls)} 个 URL（来自 {args.cache}）…")
    settings = Settings.from_mapping({"FETCHER": Fetcher.HTTP.value}, env_file=ROOT / ".env")
    http_pages = build_live_fetcher(settings).fetch_all(urls)
    by_url = {page.url: page for page in http_pages}

    steel_ok = steel_usable = http_ok = http_usable = 0
    steel_only: list[tuple[str, str]] = []
    both_usable = 0
    reason_counts: Counter[str] = Counter()
    length_deltas: list[float] = []

    for url, steel in rows:
        http = by_url[url]
        s_usable, _s_reason = is_usable_page(steel)
        h_usable, h_reason = is_usable_page(http)
        steel_ok += int(steel.ok)
        http_ok += int(http.ok)
        steel_usable += int(s_usable)
        http_usable += int(h_usable)
        if s_usable and h_usable:
            both_usable += 1
            s_len = len(steel.markdown or "")
            h_len = len(http.markdown or "")
            if s_len:
                length_deltas.append(h_len / s_len)
        if s_usable and not h_usable:
            why = str(h_reason) if http.ok and h_reason is not None else _short_reason(http.error)
            reason_counts[why] += 1
            detail = why if http.ok else (http.error or why)[:120]
            steel_only.append((url, detail))

    n = len(rows)
    print("\n=== 可用率 ===")
    print(f"  Steel  ok={steel_ok}/{n}  usable={steel_usable}/{n} ({steel_usable / n:.1%})")
    print(f"  HTTP   ok={http_ok}/{n}  usable={http_usable}/{n} ({http_usable / n:.1%})")
    print(f"  两边都 usable：{both_usable}/{n}")
    if length_deltas:
        avg = sum(length_deltas) / len(length_deltas)
        print(f"  两边都 usable 时，HTTP 正文长度 / Steel 正文长度 均值：{avg:.2f}")

    print("\n=== Steel usable、HTTP 不可用（前 30）===")
    for url, why in steel_only[:30]:
        print(f"  {why:<16} {url}")
    if len(steel_only) > 30:
        print(f"  … 另有 {len(steel_only) - 30} 条")
    print("\n原因汇总：", dict(reason_counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
