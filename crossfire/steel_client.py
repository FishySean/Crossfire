"""兼容层，第 4 步删除。实现已搬到 crossfire/adapters/steel/。这里不许有任何逻辑。

scripts/prefetch.py、scripts/probe.py 和 tests/test_page_usability.py 还在用这里的 dict 接口。
"""

from crossfire.adapters.steel.fetchers import CACHE_ROOT, DEFAULT_CONCURRENCY, MAX_RETRIES, cache_path
from crossfire.adapters.steel.legacy import (
    UNUSABLE_EMPTY,
    UNUSABLE_ERROR_TITLE,
    UNUSABLE_FETCH_FAILED,
    UNUSABLE_NAV_SKELETON,
    UNUSABLE_TOO_SHORT,
    _shape,
    fetch_live,
    fetch_page,
    fetch_pages,
    is_usable_page,
)

__all__ = [
    "CACHE_ROOT",
    "DEFAULT_CONCURRENCY",
    "MAX_RETRIES",
    "UNUSABLE_EMPTY",
    "UNUSABLE_ERROR_TITLE",
    "UNUSABLE_FETCH_FAILED",
    "UNUSABLE_NAV_SKELETON",
    "UNUSABLE_TOO_SHORT",
    "_shape",
    "cache_path",
    "fetch_live",
    "fetch_page",
    "fetch_pages",
    "is_usable_page",
]
