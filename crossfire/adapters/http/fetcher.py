"""直接 HTTP 下载 + 正文提取。不依赖 Steel，也不伪装成浏览器。"""

from __future__ import annotations

import asyncio
import re
import sys
from collections.abc import Awaitable, Callable, Sequence
from email.message import Message
from importlib.metadata import PackageNotFoundError, version
import httpx
from trafilatura import extract as trafilatura_extract
from trafilatura.metadata import extract_metadata

from crossfire.application.ports import Clock, OnPage
from crossfire.domain import Link, Mode, Page, SourceIndex

try:
    PACKAGE_VERSION = version("crossfire")
except PackageNotFoundError:
    PACKAGE_VERSION = "1.0.1"

# 如实表明身份。变异目标：若伪装成 Mozilla/Chrome，测试会红。
USER_AGENT = f"Crossfire/{PACKAGE_VERSION} (+https://github.com/FishySean/Crossfire)"

DEFAULT_CONCURRENCY = 8
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
# 仅对网络抖动重试；403/429/鉴权类状态码绝不重试绕过。
MAX_NETWORK_RETRIES = 2
NO_RETRY_STATUSES = frozenset({401, 403, 407, 429, 451})
HTML_TYPES = ("text/html", "application/xhtml+xml")


def _content_type(header: str | None) -> str:
    if not header:
        return ""
    message = Message()
    message["content-type"] = header
    return (message.get_content_type() or "").casefold()


def _is_html_content_type(header: str | None) -> bool:
    ctype = _content_type(header)
    return not ctype or ctype in HTML_TYPES or ctype.startswith("text/html")


def _decode_body(raw: bytes, content_type_header: str | None) -> str:
    charset = None
    if content_type_header:
        message = Message()
        message["content-type"] = content_type_header
        charset = message.get_content_charset()
    if charset:
        try:
            return raw.decode(charset)
        except (LookupError, UnicodeDecodeError):
            pass
    for encoding in ("utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_links(html: str, base_url: str) -> tuple[Link, ...]:
    hrefs = re.findall(
        r"""<a\s[^>]*href=["']([^"'#]+)["'][^>]*>(.*?)</a>""",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    links: list[Link] = []
    seen: set[str] = set()
    for href, inner in hrefs[:80]:
        text = re.sub(r"<[^>]+>", "", inner)
        text = re.sub(r"\s+", " ", text).strip()
        url = str(httpx.URL(base_url).join(href))
        if url in seen:
            continue
        seen.add(url)
        links.append(Link(text=text[:200] or url, url=url))
    return tuple(links)


def html_to_page(url: str, html: str, *, status_code: int, fetched_at) -> Page:
    """把 HTML 转成与 Steel 相同形状的 Page（markdown + links）。"""
    metadata = extract_metadata(html, default_url=url)
    title = (metadata.title if metadata else None) or None
    markdown = trafilatura_extract(
        html,
        url=url,
        output_format="markdown",
        include_links=True,
        include_comments=False,
        favor_recall=True,
        with_metadata=False,
    )
    return Page(
        url=url,
        ok=True,
        title=title,
        markdown=markdown or "",
        links=_extract_links(html, url),
        error=None,
        status_code=status_code,
        fetched_at=fetched_at,
    )


def failed_page(url: str, *, error: str, status_code: int | None, fetched_at) -> Page:
    return Page(url=url, ok=False, error=error, status_code=status_code, fetched_at=fetched_at)


class HttpPageFetcher:
    """用 httpx 直接下载 HTML，trafilatura 抽正文成 markdown。

    选型：trafilatura 专做网页正文抽取，自带 markdown 输出和多编码处理；
    比 readability+markdownify 少一层转换，依赖更少。不跑浏览器，遇 JS 壳页会失败——
    这是刻意的：换来源，不硬闯。
    """

    mode = Mode.LIVE

    def __init__(
        self,
        *,
        clock: Clock,
        concurrency: int = DEFAULT_CONCURRENCY,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes 必须是正数")
        self._clock = clock
        self._concurrency = concurrency
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes
        self._sleep = sleep or asyncio.sleep
        self._client_factory = client_factory or self._default_client

    def _default_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"},
            follow_redirects=True,
            timeout=httpx.Timeout(self._timeout),
        )

    def fetch_all(self, urls: Sequence[str], on_page: OnPage | None = None) -> list[Page]:
        return asyncio.run(self.fetch_all_async(urls, on_page))

    async def fetch_all_async(self, urls: Sequence[str], on_page: OnPage | None = None) -> list[Page]:
        client = self._client_factory()
        semaphore = asyncio.Semaphore(self._concurrency)

        async def fetch_one(index: int, url: str) -> Page:
            async with semaphore:
                page = await self._fetch_one(client, url)
            if on_page:
                on_page(SourceIndex(index), page)
            return page

        try:
            return list(await asyncio.gather(*(fetch_one(i, url) for i, url in enumerate(urls))))
        finally:
            await client.aclose()

    async def _fetch_one(self, client: httpx.AsyncClient, url: str) -> Page:
        fetched_at = self._clock.now()
        last_error: Exception | None = None
        for attempt in range(MAX_NETWORK_RETRIES + 1):
            try:
                return await self._download(client, url, fetched_at)
            except httpx.HTTPStatusError as error:
                # 按设计：鉴权/限流/拒绝访问不重试。
                return failed_page(
                    url,
                    error=f"HTTP {error.response.status_code}: {error}",
                    status_code=error.response.status_code,
                    fetched_at=fetched_at,
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as error:
                last_error = error
                if attempt == MAX_NETWORK_RETRIES:
                    break
                delay = 2**attempt
                print(
                    f"[http] 网络错误 {url} — 退避 {delay}s 后第 {attempt + 1}/{MAX_NETWORK_RETRIES} 次重试：{error}",
                    file=sys.stderr,
                )
                await self._sleep(delay)
            except Exception as error:
                return failed_page(url, error=f"{type(error).__name__}: {error}", status_code=None, fetched_at=fetched_at)
        return failed_page(
            url,
            error=f"{type(last_error).__name__}: {last_error}" if last_error else "未知网络错误",
            status_code=None,
            fetched_at=fetched_at,
        )

    async def _download(self, client: httpx.AsyncClient, url: str, fetched_at) -> Page:
        # 入口层已校验；这里再挡一层，避免缓存/旧数据把空白 URL 送进 httpx。
        if any(character.isspace() for character in url):
            return failed_page(
                url,
                error=f"非法 URL（含空白字符）：{url!r}",
                status_code=None,
                fetched_at=fetched_at,
            )
        async with client.stream("GET", url) as response:
            status = response.status_code
            if status in NO_RETRY_STATUSES:
                # 不 raise HTTPStatusError 走重试路径——直接失败。
                return failed_page(
                    url,
                    error=f"站点拒绝访问（HTTP {status}），不重试绕过",
                    status_code=status,
                    fetched_at=fetched_at,
                )
            if status >= 400:
                return failed_page(
                    url,
                    error=f"HTTP {status}",
                    status_code=status,
                    fetched_at=fetched_at,
                )

            content_type = response.headers.get("content-type")
            if not _is_html_content_type(content_type):
                return failed_page(
                    url,
                    error=f"不支持的内容类型：{_content_type(content_type) or content_type!r}（只要 HTML）",
                    status_code=status,
                    fetched_at=fetched_at,
                )

            length_header = response.headers.get("content-length")
            if length_header:
                try:
                    if int(length_header) > self._max_bytes:
                        return failed_page(
                            url,
                            error=f"页面超过大小上限 {self._max_bytes} 字节（Content-Length={length_header}）",
                            status_code=status,
                            fetched_at=fetched_at,
                        )
                except ValueError:
                    pass

            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > self._max_bytes:
                    return failed_page(
                        url,
                        error=f"页面超过大小上限 {self._max_bytes} 字节",
                        status_code=status,
                        fetched_at=fetched_at,
                    )
                chunks.append(chunk)

            raw = b"".join(chunks)
            html = _decode_body(raw, content_type)
            return html_to_page(url, html, status_code=status, fetched_at=fetched_at)
