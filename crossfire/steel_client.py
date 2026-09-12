import asyncio
import os
import re
import sys
import time

from dotenv import load_dotenv
from steel import AsyncSteel, RateLimitError, Steel

load_dotenv()

MAX_RETRIES = 3
DEFAULT_CONCURRENCY = 8

# 可用性阈值：都是模块级常量，方便按实际抓取情况调。
MIN_CONTENT_CHARS = 500  # 正文总长度下限（软屏蔽页通常只有几十字符）
MIN_PROSE_CHARS = 600  # 去掉链接文字后，成句正文的长度下限
MIN_PROSE_LINE_CHARS = 60  # 一行要多长才算“正文”而不是导航条目
MAX_LINK_TEXT_RATIO = 0.85  # 链接文字占可见文字的比例上限（骨架页 >0.9，导航多的正常页约 0.6-0.75）
ERROR_TITLE_PATTERNS = (
    "page not found",
    "not found",
    "404",
    "403",
    "access denied",
    "attention required",
    "just a moment",
    "are you a robot",
)

UNUSABLE_FETCH_FAILED = "fetch_failed"
UNUSABLE_EMPTY = "empty_content"
UNUSABLE_TOO_SHORT = "too_short"
UNUSABLE_ERROR_TITLE = "error_page_title"
UNUSABLE_NAV_SKELETON = "nav_skeleton"

_MARKDOWN_LINK = re.compile(r"\[([^\]\n]*)\]\(([^)\s]*)[^)]*\)")


def _strip_links(text: str) -> tuple[str, int]:
    """返回 (去掉链接后的文字, 链接文字字符数)。"""
    link_chars = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal link_chars
        link_chars += len(match.group(1).strip())
        return " "

    return _MARKDOWN_LINK.sub(replace, text), link_chars


def _prose_chars(text_without_links: str) -> int:
    """统计看起来像正文的字符数：足够长、且不是纯列表/导航条目的行。"""
    total = 0
    for line in text_without_links.splitlines():
        stripped = line.strip().lstrip("#*->|• ").strip()
        if len(stripped) >= MIN_PROSE_LINE_CHARS:
            total += len(stripped)
    return total


def is_usable_page(result: dict) -> tuple[bool, str]:
    """判断一次抓取结果是否可用。

    覆盖“HTTP 200 但内容废掉”的几类情况：反爬软屏蔽（内容极短）、
    软 404（标题写着 not found / 404）、以及数据中心 IP 只拿到导航骨架页
    （字符数不少，但全是链接、没有成句正文）。

    返回 (是否可用, 不可用原因)。可用时原因为空字符串。
    """
    if not result or not result.get("ok"):
        return False, UNUSABLE_FETCH_FAILED

    markdown = (result.get("markdown") or "").strip()
    if not markdown:
        return False, UNUSABLE_EMPTY

    title = (result.get("title") or "").strip().lower()
    if any(pattern in title for pattern in ERROR_TITLE_PATTERNS):
        return False, UNUSABLE_ERROR_TITLE

    if len(markdown) < MIN_CONTENT_CHARS:
        return False, UNUSABLE_TOO_SHORT

    without_links, link_chars = _strip_links(markdown)
    visible_chars = link_chars + len(re.sub(r"\s+", "", without_links))
    link_ratio = link_chars / visible_chars if visible_chars else 1.0
    if link_ratio > MAX_LINK_TEXT_RATIO or _prose_chars(without_links) < MIN_PROSE_CHARS:
        return False, UNUSABLE_NAV_SKELETON

    return True, ""


def _mark_usable(result: dict) -> dict:
    usable, reason = is_usable_page(result)
    result["usable"] = usable
    result["unusable_reason"] = reason
    return result


def _shape(url: str, result=None, error: Exception | None = None) -> dict:
    if error is not None:
        message = str(error)
        response = getattr(error, "response", None)
        if response is not None:
            message = f"{message}\n{response.text}"
        return _mark_usable(
            {
                "url": url,
                "ok": False,
                "title": None,
                "markdown": None,
                "links": [],
                "error": message,
                "status_code": getattr(error, "status_code", None),
            }
        )
    return _mark_usable(
        {
            "url": url,
            "ok": True,
            "title": result.metadata.title,
            "markdown": result.content.markdown or "",
            "links": [{"text": link.text, "url": link.url} for link in result.links],
            "error": None,
            "status_code": result.metadata.status_code,
        }
    )


def fetch_page(url: str) -> dict:
    client = Steel(steel_api_key=os.environ.get("STEEL_API_KEY"))
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


async def fetch_pages(urls: list[str], concurrency: int = DEFAULT_CONCURRENCY) -> list[dict]:
    client = AsyncSteel(steel_api_key=os.environ.get("STEEL_API_KEY"))
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_one(url: str) -> dict:
        async with semaphore:
            for attempt in range(MAX_RETRIES + 1):
                try:
                    scraped = await client.scrape(url=url, format=["markdown"])
                    return _shape(url, result=scraped)
                except RateLimitError as e:
                    if attempt == MAX_RETRIES:
                        return _shape(url, error=e)
                    delay = 2**attempt
                    print(
                        f"[steel] 429 {url} — 退避 {delay}s 后第 {attempt + 1}/{MAX_RETRIES} 次重试",
                        file=sys.stderr,
                    )
                    await asyncio.sleep(delay)
                except Exception as e:
                    return _shape(url, error=e)

    try:
        return list(await asyncio.gather(*(fetch_one(url) for url in urls)))
    finally:
        await client.close()


def fetch_live(url: str) -> dict:
    client = Steel(steel_api_key=os.environ.get("STEEL_API_KEY"))
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
