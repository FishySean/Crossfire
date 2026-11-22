"""HttpPageFetcher：离线 MockTransport，不访问网络。"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from crossfire.adapters.http import USER_AGENT, HttpPageFetcher
from crossfire.adapters.http.fetcher import DEFAULT_MAX_BYTES, NO_RETRY_STATUSES, html_to_page
from tests.fakes import FakeClock

FIXTURES = Path(__file__).parent / "fixtures" / "html"
ARTICLE = (FIXTURES / "article.html").read_bytes()
GB18030 = (FIXTURES / "gb18030.html").read_bytes()


def _client_for(handler):
    return lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def test_user_agent_is_honest_crossfire_not_a_browser():
    """变异目标：伪装成浏览器的 User-Agent。"""
    assert USER_AGENT.startswith("Crossfire/")
    assert "github.com/FishySean/Crossfire" in USER_AGENT
    assert "Mozilla" not in USER_AGENT
    assert "Chrome" not in USER_AGENT
    assert "Safari" not in USER_AGENT


def test_fetches_html_and_extracts_markdown():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"] == USER_AGENT
        return httpx.Response(200, content=ARTICLE, headers={"content-type": "text/html; charset=utf-8"})

    pages = HttpPageFetcher(clock=FakeClock(), client_factory=_client_for(handler)).fetch_all(
        ["https://example.com/python"]
    )
    assert len(pages) == 1
    page = pages[0]
    assert page.ok is True
    assert page.title in {"Python Releases", "Python 3.15"}
    assert "3.15.2" in (page.markdown or "")
    assert page.fetched_at is not None


def test_403_fails_without_retry():
    """变异目标：403 之后仍然重试。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403, text="forbidden")

    pages = HttpPageFetcher(clock=FakeClock(), client_factory=_client_for(handler)).fetch_all(
        ["https://blocked.example/"]
    )
    assert calls["n"] == 1
    assert pages[0].ok is False
    assert pages[0].status_code == 403
    assert "不重试" in (pages[0].error or "")


def test_429_is_in_no_retry_set_and_fails_once():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, text="slow down")

    pages = HttpPageFetcher(clock=FakeClock(), client_factory=_client_for(handler)).fetch_all(
        ["https://rate.example/"]
    )
    assert 429 in NO_RETRY_STATUSES
    assert calls["n"] == 1
    assert pages[0].ok is False and pages[0].status_code == 429


def test_oversized_content_length_rejected():
    """变异目标：不限制下载大小。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<html><body>tiny</body></html>",
            headers={"content-type": "text/html", "content-length": str(DEFAULT_MAX_BYTES + 1)},
        )

    pages = HttpPageFetcher(clock=FakeClock(), client_factory=_client_for(handler)).fetch_all(
        ["https://huge.example/"]
    )
    assert pages[0].ok is False
    assert "大小上限" in (pages[0].error or "")


def test_streamed_body_over_max_bytes_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        # 不设 content-length，靠流式累计触发上限。
        return httpx.Response(
            200,
            content=b"x" * (DEFAULT_MAX_BYTES + 100),
            headers={"content-type": "text/html"},
        )

    pages = HttpPageFetcher(
        clock=FakeClock(),
        max_bytes=1024,
        client_factory=_client_for(handler),
    ).fetch_all(["https://stream.example/"])
    assert pages[0].ok is False
    assert "大小上限" in (pages[0].error or "")


def test_non_html_is_unsupported():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})

    pages = HttpPageFetcher(clock=FakeClock(), client_factory=_client_for(handler)).fetch_all(
        ["https://docs.example/a.pdf"]
    )
    assert pages[0].ok is False
    assert "不支持" in (pages[0].error or "")
    assert "pdf" in (pages[0].error or "").casefold()


def test_timeout_is_recorded_as_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    pages = HttpPageFetcher(clock=FakeClock(), client_factory=_client_for(handler)).fetch_all(
        ["https://slow.example/"]
    )
    assert pages[0].ok is False
    assert "Timeout" in (pages[0].error or "") or "timeout" in (pages[0].error or "").casefold()


def test_gb18030_page_decodes():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=GB18030, headers={"content-type": "text/html; charset=gb18030"})

    pages = HttpPageFetcher(clock=FakeClock(), client_factory=_client_for(handler)).fetch_all(
        ["https://zh.example/"]
    )
    assert pages[0].ok is True
    assert "3.15.2" in (pages[0].markdown or "")
    assert pages[0].title in {"中文页面", "版本说明"}


def test_html_to_page_matches_steel_shape():
    page = html_to_page("https://example.com/", ARTICLE.decode("utf-8"), status_code=200, fetched_at=FakeClock().now())
    assert page.ok and page.markdown and page.title
    assert page.status_code == 200


def test_max_bytes_must_be_positive():
    with pytest.raises(ValueError, match="max_bytes"):
        HttpPageFetcher(clock=FakeClock(), max_bytes=0)
