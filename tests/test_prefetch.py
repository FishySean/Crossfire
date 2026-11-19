"""预抓取：PrefetchPages 用例 + CachePageStore。存下去的页面必须能被 CachedPageFetcher 原样读回来。"""

import pytest

from crossfire.adapters.steel import CachedPageFetcher, cache_path
from crossfire.adapters.storage import CachePageStore, MissingFetchTimeError
from crossfire.application.use_cases import PrefetchPages
from crossfire.domain import Question
from tests.fakes import FakeFetcher

QUESTION = Question.from_dict(
    {
        "id": "pre-q",
        "question": "?",
        "sources": [
            {"url": "https://a.example/x", "tier": "primary"},
            {"url": "https://b.example/y", "tier": "news"},
        ],
    }
)
URLS = [s.url for s in QUESTION.sources]


class MemoryStore:
    def __init__(self):
        self.pages = []

    def save(self, page):
        self.pages.append(page)
        return f"memory://{len(self.pages)}"


def test_every_page_is_stored_including_failures():
    store = MemoryStore()
    stored = PrefetchPages(FakeFetcher(failing_urls={URLS[1]}), store).execute(QUESTION)

    assert [s.page.url for s in stored] == URLS
    assert [s.page.ok for s in stored] == [True, False]
    assert [s.location for s in stored] == ["memory://1", "memory://2"]
    assert store.pages == [s.page for s in stored]


def test_cache_store_round_trips_through_the_cached_fetcher(tmp_path):
    pages = FakeFetcher(failing_urls={URLS[1]}).fetch_all(URLS)
    store = CachePageStore(tmp_path / "pre-q")
    locations = [store.save(page) for page in pages]

    assert locations == [str(cache_path(tmp_path / "pre-q", url)) for url in URLS]
    assert list((tmp_path / "pre-q").glob("*.tmp")) == []
    assert CachedPageFetcher(tmp_path / "pre-q").fetch_all(URLS) == pages


def test_cache_store_keeps_the_fetch_time(tmp_path):
    [page] = FakeFetcher().fetch_all(URLS[:1])
    CachePageStore(tmp_path).save(page)
    [read_back] = CachedPageFetcher(tmp_path).fetch_all(URLS[:1])
    assert read_back.fetched_at == page.fetched_at is not None


def test_cache_store_refuses_a_page_without_fetch_time(tmp_path):
    [page] = FakeFetcher(fetched_at=None).fetch_all(URLS[:1])
    with pytest.raises(MissingFetchTimeError, match="fetched_at"):
        CachePageStore(tmp_path).save(page)
    assert list(tmp_path.iterdir()) == []


def test_saving_the_same_url_again_overwrites(tmp_path):
    [page] = FakeFetcher().fetch_all(URLS[:1])
    store = CachePageStore(tmp_path)
    first = store.save(page)
    assert store.save(page) == first
    assert len(list(tmp_path.glob("*.json"))) == 1
