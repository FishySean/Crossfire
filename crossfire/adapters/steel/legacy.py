"""返回 dict 的旧抓取接口，供 scripts/prefetch.py、scripts/probe.py 和 crossfire.steel_client 兼容层使用。

第 4 步脚本改用 PageFetcher 之后删除。fetch_live 目前没有调用方，按原样保留到第 4 步再决定去留。
"""

import os
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from steel import RateLimitError, Steel

from crossfire.adapters.steel.fetchers import (
    DEFAULT_CONCURRENCY,
    MAX_RETRIES,
    CachedPageFetcher,
    SteelPageFetcher,
    to_page,
)
from crossfire.application.records import page_record
from crossfire.domain import Page, SourceIndex, UnusableReason
from crossfire.domain import is_usable_page as _is_usable

UNUSABLE_FETCH_FAILED = UnusableReason.FETCH_FAILED
UNUSABLE_EMPTY = UnusableReason.EMPTY
UNUSABLE_TOO_SHORT = UnusableReason.TOO_SHORT
UNUSABLE_ERROR_TITLE = UnusableReason.ERROR_TITLE
UNUSABLE_NAV_SKELETON = UnusableReason.NAV_SKELETON


def is_usable_page(result: dict[str, Any]) -> tuple[bool, str]:
    """domain.usability.is_usable_page 的 dict 版本，可用时原因为空字符串。"""
    if not result or not result.get("ok"):
        return False, UNUSABLE_FETCH_FAILED.value
    usable, reason = _is_usable(Page.from_dict(result))
    return usable, "" if reason is None else reason.value


def _shape(url: str, result: Any = None, error: Exception | None = None) -> dict[str, Any]:
    return page_record(to_page(url, result=result, error=error))


def _steel_client() -> Steel:
    load_dotenv()
    return Steel(steel_api_key=os.environ.get("STEEL_API_KEY"))


def fetch_page(url: str) -> dict[str, Any]:
    client = _steel_client()
    for attempt in range(MAX_RETRIES + 1):
        try:
            return _shape(url, result=client.scrape(url=url, format=["markdown"]))
        except RateLimitError as e:
            if attempt == MAX_RETRIES:
                return _shape(url, error=e)
            delay = 2**attempt
            print(
                f"[steel] 429 {url} — 退避 {delay}s 后第 {attempt + 1}/{MAX_RETRIES} 次重试",
                file=sys.stderr,
            )
            time.sleep(delay)
        except Exception as e:
            return _shape(url, error=e)
    raise AssertionError("unreachable")


async def fetch_pages(
    urls: Sequence[str],
    concurrency: int = DEFAULT_CONCURRENCY,
    use_cache: bool = False,
    cache_dir: Path | None = None,
    on_page: Callable[[int, dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    def forward(index: SourceIndex, page: Page) -> None:
        if on_page:
            on_page(index, page_record(page))

    if use_cache:
        if cache_dir is None:
            raise ValueError("use_cache=True 时必须给 cache_dir")
        pages = CachedPageFetcher(cache_dir).fetch_all(urls, forward)
    else:
        load_dotenv()
        fetcher = SteelPageFetcher(os.environ.get("STEEL_API_KEY"), concurrency)
        pages = await fetcher.fetch_all_async(urls, forward)
    return [page_record(page) for page in pages]


def fetch_live(url: str) -> dict[str, Any]:
    client = _steel_client()
    session = None
    try:
        session = client.sessions.create()
        result = _shape(url, result=client.scrape(url=url, format=["markdown"]))
        result["session_viewer_url"] = session.session_viewer_url
        return result
    except Exception as e:
        result = _shape(url, error=e)
        result["session_viewer_url"] = getattr(session, "session_viewer_url", None) if session else None
        return result
    finally:
        if session is not None:
            client.sessions.release(session.id)
