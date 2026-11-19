from dataclasses import dataclass

from crossfire.application.ports import PageFetcher, PageStore
from crossfire.domain import Page, Question


@dataclass(frozen=True)
class StoredPage:
    page: Page
    location: str


class PrefetchPages:
    """把一个问题的所有来源实时抓一遍存起来，给 cached 模式和现场演示当降落伞。"""

    def __init__(self, fetcher: PageFetcher, store: PageStore) -> None:
        self._fetcher = fetcher
        self._store = store

    def execute(self, question: Question) -> list[StoredPage]:
        pages = self._fetcher.fetch_all([source.url for source in question.sources])
        return [StoredPage(page=page, location=self._store.save(page)) for page in pages]
