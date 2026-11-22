"""NLI 日期回退：published_date 没有时用 content_date，避免 train/serve skew。"""

from crossfire.adapters.nli.encoding import UNKNOWN_DATE, effective_date, encode_pair, encode_pair_row


def test_effective_date_prefers_published_then_content():
    assert effective_date("2024-10-07", "2020-01-01") == "2024-10-07"
    assert effective_date(None, "2024-10-07") == "2024-10-07"
    assert effective_date("", "2024-10-07") == "2024-10-07"
    assert effective_date(None, None) is None
    assert effective_date("  ", "  ") is None


def test_encode_pair_falls_back_to_content_date():
    # 变异目标：若推理端忽略 content_date，回退后仍会写成 unknown。
    encoded = encode_pair(
        "最新稳定版？",
        "3.13 是最新版",
        "3.14.7 是最新版",
        published_date_a=None,
        published_date_b=None,
        content_date_a="2024-10-07",
        content_date_b="2026-09-12",
    )
    assert "published: 2024-10-07" in encoded.premise
    assert "published: 2026-09-12" in encoded.hypothesis
    assert UNKNOWN_DATE not in encoded.as_single_string()


def test_encode_pair_row_reads_content_date_columns():
    encoded = encode_pair_row(
        {
            "question": "q",
            "claim_a": "a",
            "claim_b": "b",
            "published_date_a": None,
            "published_date_b": None,
            "content_date_a": "2024-10-07",
            "content_date_b": "2025-01-01",
        }
    )
    assert "2024-10-07" in encoded.premise
    assert "2025-01-01" in encoded.hypothesis


def test_old_claim_without_content_date_still_loads():
    from crossfire.domain import Claim

    claim = Claim.from_dict(
        {
            "url": "https://a.example/",
            "tier": "primary",
            "claim": "x",
            "evidence": "e",
            "source_type": "official_documentation",
            "confidence": 0.9,
            "published_date": None,
            "usage": {"input_tokens": 1, "output_tokens": 1, "requests": 1},
        }
    )
    assert claim.content_date is None and claim.content_date_evidence is None
    assert "content_date" not in claim.to_dict()
