import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from steel import AsyncSteel, RateLimitError, Steel

from crossfire.domain.models import Page
from crossfire.domain.usability import UnusableReason
from crossfire.domain.usability import is_usable_page as _is_usable

load_dotenv()

MAX_RETRIES = 3
DEFAULT_CONCURRENCY = 8
CACHE_ROOT = Path(__file__).resolve().parents[1] / "out" / "cache"


def cache_path(cache_dir: Path, url: str) -> Path:
    return Path(cache_dir) / f"{hashlib.sha256(url.encode()).hexdigest()[:16]}.json"


UNUSABLE_FETCH_FAILED = UnusableReason.FETCH_FAILED
UNUSABLE_EMPTY = UnusableReason.EMPTY
UNUSABLE_TOO_SHORT = UnusableReason.TOO_SHORT
UNUSABLE_ERROR_TITLE = UnusableReason.ERROR_TITLE
UNUSABLE_NAV_SKELETON = UnusableReason.NAV_SKELETON


def is_usable_page(result: dict) -> tuple[bool, str]:
    """domain.usability.is_usable_page 的 dict 版本，可用时原因为空字符串。"""
    if not result or not result.get("ok"):
        return False, UNUSABLE_FETCH_FAILED.value
    usable, reason = _is_usable(Page.from_dict(result))
    return usable, "" if reason is None else reason.value


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


async def fetch_pages(
    urls: list[str],
    concurrency: int = DEFAULT_CONCURRENCY,
    use_cache: bool = False,
    cache_dir: Path | None = None,
    on_page=None,
) -> list[dict]:
    client = AsyncSteel(steel_api_key=os.environ.get("STEEL_API_KEY"))
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_one(index: int, url: str) -> dict:
        if use_cache:
            path = cache_path(cache_dir, url)
            if path.exists():
                page = json.loads(path.read_text(encoding="utf-8"))
            else:
                page = _shape(url, error=FileNotFoundError(f"缓存缺失：{path}"))
            if on_page:
                on_page(index, page)
            return page

        async with semaphore:
            for attempt in range(MAX_RETRIES + 1):
                try:
                    page = _shape(url, result=await client.scrape(url=url, format=["markdown"]))
                    break
                except RateLimitError as e:
                    if attempt == MAX_RETRIES:
                        page = _shape(url, error=e)
                        break
                    delay = 2**attempt
                    print(
                        f"[steel] 429 {url} — 退避 {delay}s 后第 {attempt + 1}/{MAX_RETRIES} 次重试",
                        file=sys.stderr,
                    )
                    await asyncio.sleep(delay)
                except Exception as e:
                    page = _shape(url, error=e)
                    break
        if on_page:
            on_page(index, page)
        return page

    try:
        return list(await asyncio.gather(*(fetch_one(i, url) for i, url in enumerate(urls))))
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
