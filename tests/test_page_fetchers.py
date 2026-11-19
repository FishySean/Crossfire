"""fetch_pages 的特征测试：缓存读取、缓存缺失、429 退避、on_page 回调、客户端关闭。

被测实现由 fetcher fixture 提供，断言只认页面 dict 的 url / ok / error / markdown
和 on_page(index, page) 回调。同一组断言跑两遍：legacy 是 steel_client.fetch_pages 这个
dict 接口（scripts/prefetch.py 还在用），adapter 是 SteelPageFetcher / CachedPageFetcher。
"""

import asyncio
import json
import socket
from types import SimpleNamespace

import httpx
import pytest
import steel

import crossfire.adapters.steel.fetchers
import crossfire.steel_client
from crossfire.adapters.steel import CachedPageFetcher, SteelPageFetcher
from crossfire.application.records import page_record
from crossfire.domain import Mode
from crossfire.steel_client import cache_path

URLS = ["https://a.example/", "https://b.example/", "https://c.example/"]
REQUEST = httpx.Request("POST", "https://api.steel.invalid/v1/scrape")
REAL_SLEEP = asyncio.sleep


def scrape_result(url):
    return SimpleNamespace(
        metadata=SimpleNamespace(title=f"标题 {url}", status_code=200),
        content=SimpleNamespace(markdown=f"正文 {url}"),
        links=[SimpleNamespace(text="Docs", url="/docs")],
    )


def rate_limited():
    return steel.RateLimitError("rate limited", response=httpx.Response(429, request=REQUEST, text="slow down"), body=None)


class FakeSteel:
    """按 URL 预设每次 scrape 的结果；元素是异常就抛出。delays 让完成顺序与 urls 顺序不同。"""

    def __init__(self, script=None, delays=None):
        self.script = {url: list(items) for url, items in (script or {}).items()}
        self.delays = delays or {}
        self.calls = []
        self.closed = 0

    async def scrape(self, url, format):
        self.calls.append(url)
        await REAL_SLEEP(self.delays.get(url, 0))
        items = self.script.get(url)
        item = items.pop(0) if items else scrape_result(url)
        if isinstance(item, BaseException):
            raise item
        return item

    async def close(self):
        self.closed += 1


def _refuse(*args, **kwargs):
    raise AssertionError("测试里不允许任何真实网络调用")


@pytest.fixture(params=["legacy", "adapter"])
def fetcher(request, monkeypatch):
    """返回 install(fake_steel) -> fetch(urls, on_page, cache_dir=None)，以及记录退避的 sleeps。"""
    monkeypatch.delenv("STEEL_API_KEY", raising=False)
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    def install(fake_steel):
        if request.param == "legacy":
            monkeypatch.setattr(crossfire.adapters.steel.fetchers, "AsyncSteel", lambda **kwargs: fake_steel)
            monkeypatch.setattr(asyncio, "sleep", fake_sleep)

            def fetch(urls, on_page=None, cache_dir=None):
                return asyncio.run(
                    crossfire.steel_client.fetch_pages(
                        urls, use_cache=cache_dir is not None, cache_dir=cache_dir, on_page=on_page
                    )
                )

            return fetch

        def fetch(urls, on_page=None, cache_dir=None):
            if cache_dir is not None:
                port = CachedPageFetcher(cache_dir)
            else:
                port = SteelPageFetcher(None, client_factory=lambda: fake_steel, sleep=fake_sleep)
            forward = (lambda index, page: on_page(index, page_record(page))) if on_page else None
            return [page_record(page) for page in port.fetch_all(urls, forward)]

        return fetch

    return install, sleeps


def test_cached_mode_reads_disk_without_scraping(fetcher, tmp_path):
    install, _ = fetcher
    fake = FakeSteel()
    fetch = install(fake)
    for url in URLS:
        page = {"url": url, "ok": True, "title": "t", "markdown": f"缓存 {url}", "links": [], "error": None, "status_code": 200}
        cache_path(tmp_path, url).write_text(json.dumps(page), encoding="utf-8")

    pages = fetch(URLS, cache_dir=tmp_path)

    assert [p["markdown"] for p in pages] == [f"缓存 {url}" for url in URLS]
    assert fake.calls == []


def test_missing_cache_file_is_a_failed_page_not_an_exception(fetcher, tmp_path):
    install, _ = fetcher
    fetch = install(FakeSteel())
    page = {"url": URLS[0], "ok": True, "title": "t", "markdown": "缓存", "links": [], "error": None, "status_code": 200}
    cache_path(tmp_path, URLS[0]).write_text(json.dumps(page), encoding="utf-8")

    pages = fetch(URLS[:2], cache_dir=tmp_path)

    assert [p["ok"] for p in pages] == [True, False]
    assert "缓存缺失" in pages[1]["error"]
    assert pages[1]["url"] == URLS[1]


def test_rate_limit_backs_off_exponentially_and_recovers(fetcher):
    install, sleeps = fetcher
    fake = FakeSteel(script={URLS[0]: [rate_limited(), rate_limited(), rate_limited()]})
    pages = install(fake)(URLS[:1])

    assert pages[0]["ok"] is True
    assert fake.calls == [URLS[0]] * 4
    assert sleeps == [1, 2, 4]


def test_rate_limit_gives_up_after_three_retries(fetcher):
    install, sleeps = fetcher
    fake = FakeSteel(script={URLS[0]: [rate_limited()] * 5})
    pages = install(fake)(URLS[:1])

    assert pages[0]["ok"] is False
    assert "slow down" in pages[0]["error"]
    assert fake.calls == [URLS[0]] * 4
    assert sleeps == [1, 2, 4]


def test_other_errors_fail_the_page_without_retrying(fetcher):
    install, sleeps = fetcher
    fake = FakeSteel(script={URLS[1]: [RuntimeError("boom")]})
    pages = install(fake)(URLS)

    assert [p["ok"] for p in pages] == [True, False, True]
    assert "boom" in pages[1]["error"]
    assert fake.calls.count(URLS[1]) == 1
    assert sleeps == []


def test_on_page_called_once_per_page_with_its_url_index(fetcher):
    install, _ = fetcher
    fake = FakeSteel(delays={URLS[0]: 0.03, URLS[1]: 0.0, URLS[2]: 0.015})
    seen = []
    pages = install(fake)(URLS, on_page=lambda index, page: seen.append((index, page["url"])))

    assert sorted(seen) == list(enumerate(URLS))
    assert [url for _, url in seen] != URLS, "完成顺序应与 urls 顺序不同，否则测不出 index 是不是按完成顺序数的"
    assert [p["url"] for p in pages] == URLS


def test_cached_on_page_called_once_per_page_with_its_url_index(fetcher, tmp_path):
    """cached 模式下前端同样按 index 定位卡片，缓存缺失的页面也要回调。"""
    install, _ = fetcher
    fetch = install(FakeSteel())
    page = {"url": URLS[1], "ok": True, "title": "t", "markdown": "缓存", "links": [], "error": None, "status_code": 200}
    cache_path(tmp_path, URLS[1]).write_text(json.dumps(page), encoding="utf-8")
    seen = []

    fetch(URLS, on_page=lambda index, page: seen.append((index, page["url"], page["ok"])), cache_dir=tmp_path)

    assert sorted(seen) == [(0, URLS[0], False), (1, URLS[1], True), (2, URLS[2], False)]


def test_live_client_is_closed(fetcher):
    install, _ = fetcher
    fake = FakeSteel(script={URLS[0]: [RuntimeError("boom")]})
    install(fake)(URLS)
    assert fake.closed == 1


def test_each_fetcher_reports_its_own_mode(tmp_path):
    """结果文件里的 mode 从注入的 fetcher 读，不再由调用方另传一份。"""
    assert SteelPageFetcher(None, client_factory=FakeSteel).mode is Mode.LIVE
    assert CachedPageFetcher(tmp_path).mode is Mode.CACHED
