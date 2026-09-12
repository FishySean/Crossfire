import asyncio
import os
import sys
import time

from dotenv import load_dotenv
from steel import AsyncSteel, RateLimitError, Steel

load_dotenv()

MAX_RETRIES = 3
DEFAULT_CONCURRENCY = 8


def _shape(url: str, result=None, error: Exception | None = None) -> dict:
    if error is not None:
        message = str(error)
        response = getattr(error, "response", None)
        if response is not None:
            message = f"{message}\n{response.text}"
        return {
            "url": url,
            "ok": False,
            "title": None,
            "markdown": None,
            "links": [],
            "error": message,
            "status_code": getattr(error, "status_code", None),
        }
    return {
        "url": url,
        "ok": True,
        "title": result.metadata.title,
        "markdown": result.content.markdown or "",
        "links": [{"text": link.text, "url": link.url} for link in result.links],
        "error": None,
        "status_code": result.metadata.status_code,
    }


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
