"""网址校验：Source / CandidateSource 在入口拒绝空白和非法 URL。"""

from __future__ import annotations

import pytest

from crossfire.domain import CandidateSource, InvalidSourceUrlError, Source, Tier, clean_source_url


def test_clean_strips_edges_and_keeps_http():
    assert clean_source_url("  https://example.com/a  ") == "https://example.com/a"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/a\nb",
        "https://example.com/a b",
        "https://example.com/a\tb",
        "https://fred.example/\nseries/X",
    ],
)
def test_clean_rejects_internal_whitespace(url):
    with pytest.raises(InvalidSourceUrlError, match="空白"):
        clean_source_url(url)


def test_clean_strips_leading_newline_then_accepts():
    # 首尾空白可以剥掉；只有剥完之后中间还有空白才拒绝。
    assert clean_source_url("\nhttps://ons.example/path\n") == "https://ons.example/path"


@pytest.mark.parametrize("url", ["ftp://example.com/", "file:///tmp/x", "javascript:alert(1)", "not-a-url", ""])
def test_clean_rejects_non_http_or_empty(url):
    with pytest.raises(InvalidSourceUrlError):
        clean_source_url(url)


def test_clean_rejects_missing_host():
    with pytest.raises(InvalidSourceUrlError, match="主机"):
        clean_source_url("https:///no-host")


def test_source_constructor_strips_and_rejects():
    source = Source(url=" https://example.com/ok ", tier=Tier.NEWS)
    assert source.url == "https://example.com/ok"
    with pytest.raises(InvalidSourceUrlError, match="空白"):
        Source(url="https://example.com/has\nbreak", tier=Tier.PRIMARY)


def test_candidate_source_rejects_bad_url():
    with pytest.raises(InvalidSourceUrlError):
        CandidateSource(
            url="https://bad.example/\npath",
            title="t",
            query="q",
            suggested_tier=Tier.NEWS,
        )


def test_source_from_dict_rejects_bad_url():
    with pytest.raises(InvalidSourceUrlError):
        Source.from_dict({"url": "https://x.example/a b", "tier": "news"})
