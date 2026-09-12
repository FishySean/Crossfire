import os

from dotenv import load_dotenv
from steel import Steel

load_dotenv()


def fetch_page(url: str) -> dict:
    client = Steel(steel_api_key=os.environ.get("STEEL_API_KEY"))
    try:
        result = client.scrape(url=url, format=["markdown"])
        return {
            "url": url,
            "ok": True,
            "title": result.metadata.title,
            "markdown": result.content.markdown or "",
            "links": [{"text": link.text, "url": link.url} for link in result.links],
            "error": None,
            "status_code": result.metadata.status_code,
        }
    except Exception as e:
        error = str(e)
        response = getattr(e, "response", None)
        if response is not None:
            error = f"{error}\n{response.text}"
        return {
            "url": url,
            "ok": False,
            "title": None,
            "markdown": None,
            "links": [],
            "error": error,
            "status_code": getattr(e, "status_code", None),
        }


def fetch_live(url: str) -> dict:
    client = Steel(steel_api_key=os.environ.get("STEEL_API_KEY"))
    session = None
    try:
        session = client.sessions.create()
        result = client.scrape(url=url, format=["markdown"])
        return {
            "url": url,
            "ok": True,
            "title": result.metadata.title,
            "markdown": result.content.markdown or "",
            "links": [{"text": link.text, "url": link.url} for link in result.links],
            "session_viewer_url": session.session_viewer_url,
            "error": None,
        }
    except Exception as e:
        error = str(e)
        response = getattr(e, "response", None)
        if response is not None:
            error = f"{error}\n{response.text}"
        return {
            "url": url,
            "ok": False,
            "title": None,
            "markdown": None,
            "links": [],
            "session_viewer_url": getattr(session, "session_viewer_url", None) if session else None,
            "error": error,
        }
    finally:
        if session is not None:
            client.sessions.release(session.id)
