"""发布日期不得用 as_of 冒充：找不到就改成 null。"""

from datetime import date

import pytest

from crossfire.domain.published_dates import published_date_appears_on_page, scrub_as_of_published_date

AS_OF = date(2026, 11, 20)


def test_page_mentions_common_date_spellings():
    assert published_date_appears_on_page("checked 20 Nov 2026. Spotted a mistake?", AS_OF)
    assert published_date_appears_on_page("Updated November 20, 2026 by editors", AS_OF)
    assert published_date_appears_on_page("发布于 2026年11月20日", AS_OF)
    assert published_date_appears_on_page("iso 2026-11-20 footer", AS_OF)
    assert not published_date_appears_on_page("last edited 19 November 2026", AS_OF)
    assert not published_date_appears_on_page("no dates here", AS_OF)


def test_scrub_clears_as_of_when_page_lacks_the_date():
    # 变异目标：如果等于 as_of 仍原样放过，假日期会继续进比对。
    cleaned, warning = scrub_as_of_published_date("2026-11-20", AS_OF, "维基百科词条，没有发布日")
    assert cleaned is None
    assert warning is not None
    assert "null" in warning


def test_scrub_keeps_as_of_when_page_really_has_it():
    cleaned, warning = scrub_as_of_published_date(
        "2026-11-20", AS_OF, "vendor announcements, checked 20 Nov 2026."
    )
    assert cleaned == "2026-11-20"
    assert warning is None


def test_scrub_leaves_other_dates_alone():
    cleaned, warning = scrub_as_of_published_date("2025-01-01", AS_OF, "anything")
    assert cleaned == "2025-01-01"
    assert warning is None


def test_extractor_scrubs_fabricated_as_of_dates(capsys):
    # 变异目标：如果 extract 不调用 scrub，模型填的 as_of 会原样留下。
    from types import SimpleNamespace

    from crossfire.adapters.anthropic import ClaudeClaimExtractor, ClaudeClient
    from crossfire.domain import Page, Question, Source, Tier

    data = {
        "claim": "有 30 支球队",
        "evidence": "30 teams",
        "source_type": "news_article",
        "confidence": 0.9,
        "published_date": "2026-11-20",
    }

    class FakeMessages:
        def create(self, **kwargs):
            block = SimpleNamespace(
                type="tool_use",
                input=data,
                model_dump=lambda: {"type": "tool_use", "input": data},
            )
            return SimpleNamespace(
                stop_reason="tool_use",
                content=[block],
                usage=SimpleNamespace(input_tokens=10, output_tokens=2),
            )

    client = ClaudeClient(client=SimpleNamespace(messages=FakeMessages()), sleep=lambda delay: None)
    question = Question(
        id="nba",
        text="NBA 目前有多少支球队？",
        sources=(Source("https://espn.example/story", Tier.NEWS),),
    )
    page = Page(
        url="https://espn.example/story",
        ok=True,
        title="NBA",
        markdown="An NBA story with no publication day matching as_of.",
    )
    result = ClaudeClaimExtractor(client).extract(question, page, AS_OF)
    assert result.published_date is None
    err = capsys.readouterr().err
    assert "published_date" in err and "null" in err
