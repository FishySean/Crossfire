"""SourceFinder：只能返回搜索结果里出现过的 URL；层级配额与关键词过滤。"""

from datetime import UTC, date, datetime

import pytest

from crossfire.adapters.anthropic.source_finder import (
    ClaudeSourceFinder,
    filter_to_searched,
    normalize_url,
    search_urls_from_content,
)
from crossfire.application.use_cases.build_question_bank import (
    BuildQuestionBank,
    page_mentions_topic,
    select_by_tier_mix,
)
from crossfire.domain import (
    CandidateSource,
    DropReason,
    Page,
    ProposedQuestion,
    QuestionCategory,
    Tier,
)


AS_OF = date(2026, 11, 20)


def candidate(url: str, tier: Tier = Tier.NEWS, query: str = "q") -> CandidateSource:
    return CandidateSource(url=url, title=url, query=query, suggested_tier=tier)


def test_normalize_url_strips_fragment_and_trailing_slash():
    assert normalize_url("https://a.example/x/#frag") == "https://a.example/x"
    assert normalize_url("https://a.example/x/") == "https://a.example/x"


def test_search_urls_from_content_reads_web_search_results():
    content = [
        {
            "type": "web_search_tool_result",
            "content": [
                {"type": "web_search_result", "url": "https://a.example/1", "title": "A"},
                {"type": "web_search_result", "url": "https://b.example/2/", "title": "B"},
            ],
        }
    ]
    assert search_urls_from_content(content) == {"https://a.example/1", "https://b.example/2"}


def test_filter_drops_urls_that_were_not_in_search_results():
    # 变异目标：如果 adapter 不过滤幻觉 URL，这条会红。
    searched = {"https://real.example/page"}
    kept = filter_to_searched(
        [candidate("https://real.example/page"), candidate("https://hallucinated.example/x")],
        searched,
    )
    assert [item.url for item in kept] == ["https://real.example/page"]


def test_tier_mix_caps_each_tier_at_three():
    # 变异目标：如果层级配额不生效，会留下超过 3 个 primary。
    many = [candidate(f"https://p.example/{i}", Tier.PRIMARY) for i in range(5)]
    many += [candidate(f"https://n.example/{i}", Tier.NEWS) for i in range(5)]
    many += [candidate(f"https://a.example/{i}", Tier.AGGREGATOR) for i in range(5)]
    picked = select_by_tier_mix(many)
    assert sum(1 for c in picked if c.suggested_tier is Tier.PRIMARY) == 3
    assert sum(1 for c in picked if c.suggested_tier is Tier.NEWS) == 3
    assert sum(1 for c in picked if c.suggested_tier is Tier.AGGREGATOR) == 3
    assert len(picked) == 9


def test_page_mentions_topic_is_case_insensitive():
    assert page_mentions_topic("Python 3.15 is current", ["python", "稳定版"])
    assert not page_mentions_topic("unrelated cooking blog", ["python", "稳定版"])


class FakeProposer:
    def __init__(self, questions):
        self._questions = questions

    def propose(self, count, as_of):
        return list(self._questions)[:count]


class FakeFinder:
    def __init__(self, mapping):
        self._mapping = mapping

    def find(self, question_text, as_of):
        return list(self._mapping[question_text])


class FakeFetcher:
    def __init__(self, pages):
        self._pages = pages

    @property
    def mode(self):
        from crossfire.domain import Mode

        return Mode.LIVE

    def fetch_all(self, urls, on_page=None):
        return [self._pages[url] for url in urls]


class FakeStore:
    def __init__(self):
        self.saved = []

    def save(self, page):
        self.saved.append(page)
        return page.url


def usable_page(url: str, text: str) -> Page:
    # 足够过可用性门槛：总宽和成句正文都按显示宽度算。
    sentence = text + "。这是用于题库过滤测试的正文内容，需要足够长。"
    body = (sentence + "\n") * 40
    return Page(url=url, ok=True, title=url, markdown=body, status_code=200, fetched_at=datetime(2026, 11, 20, tzinfo=UTC))


def test_build_drops_question_with_fewer_than_five_usable_sources():
    # 变异目标：如果不足 5 个来源的题目没被丢弃，kept 会非空。
    proposed = ProposedQuestion(
        id="few-sources",
        text="X 的当前版本是什么？",
        category=QuestionCategory.TIME_LAG,
        language="zh",
        keywords=("版本", "X"),
    )
    urls = [f"https://ex.example/{i}" for i in range(3)]
    finder = FakeFinder({proposed.text: [candidate(u, Tier.PRIMARY if i < 2 else Tier.NEWS) for i, u in enumerate(urls)]})
    pages = {u: usable_page(u, "X 版本 发布") for u in urls}
    store = FakeStore()
    builder = BuildQuestionBank(FakeProposer([proposed]), finder, FakeFetcher(pages), lambda _id: store, min_usable=5)
    kept, dropped = builder.execute(1, AS_OF)
    assert kept == []
    assert len(dropped) == 1 and dropped[0].reason is DropReason.TOO_FEW_USABLE


def test_build_rejects_pages_that_miss_keywords():
    # 变异目标：如果关键词检查不生效，这篇无关页面会被留下。
    proposed = ProposedQuestion(
        id="kw",
        text="东京的人口是多少？",
        category=QuestionCategory.SCOPE,
        language="zh",
        keywords=("东京", "人口"),
    )
    good = [candidate(f"https://good.example/{i}", Tier.PRIMARY if i < 2 else Tier.NEWS) for i in range(4)]
    good += [candidate("https://good.example/agg", Tier.AGGREGATOR), candidate("https://bad.example/cook", Tier.AGGREGATOR)]
    pages = {c.url: usable_page(c.url, "东京 人口 统计") for c in good[:-1]}
    pages["https://bad.example/cook"] = usable_page("https://bad.example/cook", "番茄炒蛋 家常菜")
    store = FakeStore()
    builder = BuildQuestionBank(FakeProposer([proposed]), FakeFinder({proposed.text: good}), FakeFetcher(pages), lambda _id: store)
    kept, dropped = builder.execute(1, AS_OF)
    assert len(kept) == 1
    assert all("cook" not in s.source.url for s in kept[0].sources)
    assert any(r.reason is DropReason.KEYWORD_MISS for r in kept[0].rejected)


def test_claude_source_finder_filters_hallucinated_urls_from_tool_payload():
    class FakeMessage:
        def __init__(self):
            self.content = [
                {
                    "type": "web_search_tool_result",
                    "content": [{"type": "web_search_result", "url": "https://real.example/", "title": "R"}],
                },
                {
                    "type": "tool_use",
                    "name": "record_sources",
                    "input": {
                        "sources": [
                            {
                                "url": "https://real.example/",
                                "title": "R",
                                "query": "q",
                                "suggested_tier": "primary",
                            },
                            {
                                "url": "https://fake.example/",
                                "title": "F",
                                "query": "q",
                                "suggested_tier": "news",
                            },
                        ]
                    },
                },
            ]
            self.usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()

    class Client:
        model = "claude-sonnet-4-6"

        def create_message(self, step, **kwargs):
            return FakeMessage(), 1

    finder = ClaudeSourceFinder(Client())  # type: ignore[arg-type]
    found = finder.find("question", AS_OF)
    assert [c.url for c in found] == ["https://real.example/"]
