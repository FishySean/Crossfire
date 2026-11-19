import asyncio
import hashlib
import json
import sys
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from steel import AsyncSteel, RateLimitError

from crossfire.application.ports import OnPage
from crossfire.domain import Link, Page, SourceIndex

MAX_RETRIES = 3
DEFAULT_CONCURRENCY = 8
CACHE_ROOT = Path(__file__).resolve().parents[3] / "out" / "cache"


def cache_path(cache_dir: Path, url: str) -> Path:
    return Path(cache_dir) / f"{hashlib.sha256(url.encode()).hexdigest()[:16]}.json"


def to_page(url: str, result: Any = None, error: Exception | None = None) -> Page:
    """把 Steel 的 scrape 结果或异常转成 Page。"""
    if error is not None:
        message = str(error)
        response = getattr(error, "response", None)
        if response is not None:
            message = f"{message}\n{response.text}"
        return Page(url=url, ok=False, error=message, status_code=getattr(error, "status_code", None))
    return Page(
        url=url,
        ok=True,
        title=result.metadata.title,
        markdown=result.content.markdown or "",
        links=tuple(Link(text=link.text, url=link.url) for link in result.links),
        error=None,
        status_code=result.metadata.status_code,
    )


class SteelPageFetcher:
    """通过 Steel /v1/scrape 实时抓取。并发受 concurrency 限制，429 指数退避重试。"""

    def __init__(
        self,
        api_key: str | None,
        concurrency: int = DEFAULT_CONCURRENCY,
        *,
        client_factory: Callable[[], Any] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client_factory = client_factory or (lambda: AsyncSteel(steel_api_key=api_key))
        self._concurrency = concurrency
        self._sleep = sleep

    def fetch_all(self, urls: Sequence[str], on_page: OnPage | None = None) -> list[Page]:
        return asyncio.run(self.fetch_all_async(urls, on_page))

    async def fetch_all_async(self, urls: Sequence[str], on_page: OnPage | None = None) -> list[Page]:
        client = self._client_factory()
        semaphore = asyncio.Semaphore(self._concurrency)

        async def fetch_one(index: int, url: str) -> Page:
            async with semaphore:
                page = await self._scrape_with_backoff(client, url)
            if on_page:
                on_page(SourceIndex(index), page)
            return page

        try:
            return list(await asyncio.gather(*(fetch_one(i, url) for i, url in enumerate(urls))))
        finally:
            await client.close()

    async def _scrape_with_backoff(self, client: Any, url: str) -> Page:
        for attempt in range(MAX_RETRIES + 1):
            try:
                return to_page(url, result=await client.scrape(url=url, format=["markdown"]))
            except RateLimitError as e:
                if attempt == MAX_RETRIES:
                    return to_page(url, error=e)
                delay = 2**attempt
                print(
                    f"[steel] 429 {url} — 退避 {delay}s 后第 {attempt + 1}/{MAX_RETRIES} 次重试",
                    file=sys.stderr,
                )
                await self._sleep(delay)
            except Exception as e:
                return to_page(url, error=e)
        raise AssertionError("unreachable")


class CachedPageFetcher:
    """从 scripts/prefetch.py 写下的磁盘缓存读页面，不碰网络。缓存缺失的 URL 返回 ok=False 的页面。"""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = Path(cache_dir)

    def fetch_all(self, urls: Sequence[str], on_page: OnPage | None = None) -> list[Page]:
        pages: list[Page] = []
        for index, url in enumerate(urls):
            path = cache_path(self.cache_dir, url)
            if path.exists():
                page = Page.from_dict(json.loads(path.read_text(encoding="utf-8")))
            else:
                page = to_page(url, error=FileNotFoundError(f"缓存缺失：{path}"))
            if on_page:
                on_page(SourceIndex(index), page)
            pages.append(page)
        return pages
