"""AskQuestion：假端口覆盖正常、来源不足、费用超限、校验。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from crossfire.application.use_cases.ask_question import (
    AskQuestion,
    AskStopped,
    estimate_ask_cost,
    keywords_from_question,
    make_user_question_id,
    validate_question_text,
)
from crossfire.application.use_cases.verify_question import SavedRun
from crossfire.domain import (
    CandidateSource,
    Judgment,
    Mode,
    Page,
    Question,
    Relation,
    RunResult,
    Source,
    Tier,
    Usage,
)
from crossfire.domain.pricing import ModelPrice
from tests.fakes import CallLog, FakeExtractor, FakeJudge, FakePairer

AS_OF = date(2026, 11, 22)
PRICE = ModelPrice(input_per_mtok=3.0, output_per_mtok=15.0)


class FakeFinder:
    def __init__(self, candidates: list[CandidateSource] | None = None, *, boom: Exception | None = None) -> None:
        self.candidates = candidates or []
        self.boom = boom
        self.calls = 0

    def find(self, question_text: str, as_of: date) -> list[CandidateSource]:
        del question_text, as_of
        self.calls += 1
        if self.boom:
            raise self.boom
        return list(self.candidates)


class FakeFetcher:
    mode = Mode.LIVE

    def __init__(self, pages: dict[str, Page] | None = None) -> None:
        self.pages = pages or {}
        self.calls: list[list[str]] = []

    def fetch_all(self, urls: list[str], on_page=None) -> list[Page]:
        self.calls.append(list(urls))
        out: list[Page] = []
        for index, url in enumerate(urls):
            page = self.pages.get(
                url,
                Page(url=url, ok=True, title="t", markdown=f"keyword body for {url} " + "x" * 200),
            )
            out.append(page)
            if on_page is not None:
                on_page(index, page)
        return out


class RecordingStore:
    def __init__(self) -> None:
        self.saved: list[str] = []

    def save(self, page: Page) -> str:
        self.saved.append(page.url)
        return page.url


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, event) -> None:
        self.events.append(event.to_dict() if hasattr(event, "to_dict") else event)


def _candidate(url: str, tier: Tier = Tier.NEWS) -> CandidateSource:
    return CandidateSource(url=url, title=url, query="q", suggested_tier=tier)


def _ask(
    *,
    finder=None,
    fetcher=None,
    max_cost_usd: float = 1.0,
    pairer_free: bool = True,
    extract_log: CallLog | None = None,
) -> tuple[AskQuestion, CallLog, RecordingSink]:
    log = extract_log or CallLog()
    sink = RecordingSink()
    pages = {
        f"https://a{i}.example/": Page(
            url=f"https://a{i}.example/",
            ok=True,
            title="t",
            markdown="Python version keyword " + "正文" * 80,
        )
        for i in range(6)
    }
    candidates = [_candidate(url, Tier.NEWS if i else Tier.PRIMARY) for i, url in enumerate(pages)]

    def build_verifier(question: Question, *, has_primary: bool = True):
        del has_primary
        from crossfire.composition import assemble

        trusted = question.sources[0].url
        return assemble(
            fetcher=FakeFetcher(
                {
                    s.url: pages.get(
                        s.url,
                        Page(url=s.url, ok=True, title="t", markdown="Python keyword " + "y" * 200),
                    )
                    for s in question.sources
                }
            ),
            extractor=FakeExtractor(log),
            pairer=FakePairer(log),
            judge=FakeJudge(log, trusted),
            runs_dir=Path("/tmp/crossfire-ask-runs"),  # noqa: S108 - test only
        )

    saved: list[str] = []

    def save_question(question: Question, has_primary: bool) -> str:
        path = f"/tmp/{question.id}.yaml"
        saved.append(path)
        Path(path).write_text(
            yaml.safe_dump({**question.to_dict(), "has_primary": has_primary}, allow_unicode=True),
            encoding="utf-8",
        )
        return path

    ask = AskQuestion(
        finder=finder or FakeFinder(candidates),
        fetcher=fetcher or FakeFetcher(pages),
        store_for=lambda _qid: RecordingStore(),
        build_verifier=build_verifier,
        save_question=save_question,
        event_sink=sink,
        max_cost_usd=max_cost_usd,
        pairer_free=pairer_free,
        search_per_thousand_usd=10.0,
        steel_per_scrape_usd=0.005,
        sonnet_price=PRICE,
        clock=lambda: AS_OF,
    )
    return ask, log, sink


def test_validate_and_id_helpers():
    assert validate_question_text("  hello  ") == "hello"
    with pytest.raises(ValueError, match="空"):
        validate_question_text("   ")
    with pytest.raises(ValueError, match="最长"):
        validate_question_text("字" * 400)
    qid = make_user_question_id("Python 最新稳定版？", AS_OF)
    assert qid.startswith("u-20261122-")
    assert "Python" not in qid
    assert "最新" not in qid
    assert keywords_from_question("What is the current Node.js LTS?")


def test_happy_path_runs_extract_and_saves(tmp_path):
    from crossfire.composition import assemble

    body = "Python is the latest stable release. " + ("正文段落。" * 200)
    pages = {
        f"https://a{i}.example/": Page(url=f"https://a{i}.example/", ok=True, title="Python docs", markdown=body)
        for i in range(6)
    }
    candidates = [_candidate(url, Tier.PRIMARY if i < 2 else Tier.NEWS) for i, url in enumerate(pages)]
    log = CallLog()
    sink = RecordingSink()

    def build_verifier(question: Question, *, has_primary: bool = True):
        del has_primary
        trusted = question.sources[0].url
        return assemble(
            fetcher=FakeFetcher({s.url: pages[s.url] for s in question.sources}),
            extractor=FakeExtractor(log),
            pairer=FakePairer(log),
            judge=FakeJudge(log, trusted),
            runs_dir=tmp_path / "runs",
        )

    ask = AskQuestion(
        finder=FakeFinder(candidates),
        fetcher=FakeFetcher(pages),
        store_for=lambda _qid: RecordingStore(),
        build_verifier=build_verifier,
        save_question=lambda q, hp: str(tmp_path / f"{q.id}.yaml"),
        event_sink=sink,
        max_cost_usd=5.0,
        pairer_free=True,
        search_per_thousand_usd=10.0,
        steel_per_scrape_usd=0.005,
        sonnet_price=PRICE,
        clock=lambda: AS_OF,
    )
    result = ask.execute("Python 目前最新稳定版本是哪个？")
    assert not isinstance(result, AskStopped), getattr(result, "detail", result)
    assert "extract" in log.steps
    assert "judge" in log.steps
    assert any(e.get("type") == "sources_ready" for e in sink.events)
    assert result.has_primary is True


def test_too_few_sources_stops_before_extract():
    sink = RecordingSink()
    log = CallLog()
    ask = AskQuestion(
        finder=FakeFinder([_candidate("https://only.example/")]),
        fetcher=FakeFetcher(
            {
                "https://only.example/": Page(
                    url="https://only.example/",
                    ok=True,
                    title="t",
                    markdown="Python keyword " + ("段落。" * 200),
                )
            }
        ),
        store_for=lambda _qid: RecordingStore(),
        build_verifier=lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应构建 verifier")),
        save_question=lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应保存")),
        event_sink=sink,
        max_cost_usd=5.0,
        pairer_free=True,
        search_per_thousand_usd=10.0,
        steel_per_scrape_usd=0.005,
        sonnet_price=PRICE,
        clock=lambda: AS_OF,
    )
    result = ask.execute("Python 最新版？")
    assert isinstance(result, AskStopped)
    assert result.reason == "too_few_sources"
    assert log.steps == []
    assert any(e.get("type") == "sources_insufficient" for e in sink.events)


def test_cost_limit_rejects_without_searching():
    finder = FakeFinder([_candidate("https://a.example/")])
    ask = AskQuestion(
        finder=finder,
        fetcher=FakeFetcher(),
        store_for=lambda _qid: RecordingStore(),
        build_verifier=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no")),
        save_question=lambda *a, **k: "x",
        event_sink=RecordingSink(),
        max_cost_usd=0.01,
        pairer_free=False,
        search_per_thousand_usd=10.0,
        steel_per_scrape_usd=0.005,
        sonnet_price=PRICE,
        pair_price=PRICE,
        clock=lambda: AS_OF,
    )
    result = ask.execute("What is the current Ubuntu LTS?")
    assert isinstance(result, AskStopped)
    assert result.reason == "cost_limit"
    assert finder.calls == 0


def test_estimate_marks_over_budget():
    est = estimate_ask_cost(
        pairer_free=False,
        max_cost_usd=0.01,
        search_per_thousand_usd=10.0,
        steel_per_scrape_usd=0.005,
        sonnet_price=PRICE,
        pair_price=PRICE,
    )
    assert est.over_budget


def test_mutation_too_few_sources_must_not_call_extract():
    """变异目标：来源不足时仍然调用了提取。"""
    log = CallLog()
    called = {"extract": False}

    class BoomExtractor(FakeExtractor):
        def extract_all(self, *args, **kwargs):
            called["extract"] = True
            raise AssertionError("来源不足时不应提取")

    ask = AskQuestion(
        finder=FakeFinder([_candidate("https://only.example/")]),
        fetcher=FakeFetcher(),
        store_for=lambda _qid: RecordingStore(),
        build_verifier=lambda question, **kw: assemble_for(question, BoomExtractor(log), log),
        save_question=lambda *a, **k: "x",
        max_cost_usd=5.0,
        pairer_free=True,
        search_per_thousand_usd=10.0,
        steel_per_scrape_usd=0.005,
        sonnet_price=PRICE,
        clock=lambda: AS_OF,
    )
    result = ask.execute("Python version?")
    assert isinstance(result, AskStopped)
    assert called["extract"] is False
    assert "extract" not in log.steps


def assemble_for(question: Question, extractor, log: CallLog):
    from crossfire.composition import assemble

    return assemble(
        fetcher=FakeFetcher({s.url: Page(url=s.url, ok=True, title="t", markdown="x" * 800) for s in question.sources}),
        extractor=extractor,
        pairer=FakePairer(log),
        judge=FakeJudge(log, question.sources[0].url),
        runs_dir=Path("/tmp/crossfire-ask-mut"),  # noqa: S108
    )


def test_mutation_over_budget_must_not_search():
    """变异目标：估算超限仍然运行（去找来源）。"""
    finder = FakeFinder([_candidate("https://a.example/")])
    ask = AskQuestion(
        finder=finder,
        fetcher=FakeFetcher(),
        store_for=lambda _qid: RecordingStore(),
        build_verifier=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no")),
        save_question=lambda *a, **k: "x",
        max_cost_usd=0.01,
        pairer_free=False,
        search_per_thousand_usd=10.0,
        steel_per_scrape_usd=0.005,
        sonnet_price=PRICE,
        pair_price=PRICE,
        clock=lambda: AS_OF,
    )
    assert ask.execute("Ubuntu LTS?").reason == "cost_limit"
    assert finder.calls == 0


def test_mutation_question_id_is_not_raw_user_text():
    """变异目标：用用户输入直接拼文件名。"""
    text = "What is Python? ../etc/passwd"
    qid = make_user_question_id(text, AS_OF)
    assert "../" not in qid
    assert "passwd" not in qid
    assert text not in qid
    assert qid.startswith("u-20261122-")
    assert len(qid) < 40


def test_estimate_exposes_four_to_eight_source_range():
    est = estimate_ask_cost(
        pairer_free=True,
        max_cost_usd=1.0,
        search_per_thousand_usd=10.0,
        steel_per_scrape_usd=0.0,
        sonnet_price=PRICE,
    )
    assert est.low_sources == 4
    assert est.high_sources == 8
    assert est.low_usd == pytest.approx(est.total_usd)
    assert est.high_usd > est.low_usd
    high = estimate_ask_cost(
        pairer_free=True,
        usable_sources=8,
        max_cost_usd=1.0,
        search_per_thousand_usd=10.0,
        steel_per_scrape_usd=0.0,
        sonnet_price=PRICE,
    )
    assert est.high_usd == pytest.approx(high.total_usd)


def test_cost_limit_after_sources_found_stops_before_extract():
    """来源数确定后若超限，必须在提取前停下（二次检查）。"""
    low = estimate_ask_cost(
        pairer_free=True,
        usable_sources=4,
        max_cost_usd=1.0,
        search_per_thousand_usd=10.0,
        steel_per_scrape_usd=0.0,
        sonnet_price=PRICE,
    )
    high = estimate_ask_cost(
        pairer_free=True,
        usable_sources=6,
        max_cost_usd=1.0,
        search_per_thousand_usd=10.0,
        steel_per_scrape_usd=0.0,
        sonnet_price=PRICE,
    )
    assert high.total_usd > low.total_usd
    # 上限刚好卡在 4 来源之上：运行前能过，6 来源二次检查必须拦下。
    cap = low.total_usd + (high.total_usd - low.total_usd) * 0.1

    body = "Python keyword version stable. " + ("正文段落。" * 200)
    pages = {
        f"https://a{i}.example/": Page(url=f"https://a{i}.example/", ok=True, title="t", markdown=body)
        for i in range(6)
    }
    # 每档最多留 3 个：3 primary + 3 news → 抓取 6 个。
    candidates = [
        *[_candidate(f"https://a{i}.example/", Tier.PRIMARY) for i in range(3)],
        *[_candidate(f"https://a{i}.example/", Tier.NEWS) for i in range(3, 6)],
    ]
    sink = RecordingSink()
    extract_called = {"yes": False}

    def boom_verifier(*a, **k):
        extract_called["yes"] = True
        raise AssertionError("二次费用检查超限后不应构建 verifier / 提取")

    ask = AskQuestion(
        finder=FakeFinder(candidates),
        fetcher=FakeFetcher(pages),
        store_for=lambda _qid: RecordingStore(),
        build_verifier=boom_verifier,
        save_question=lambda *a, **k: (_ for _ in ()).throw(AssertionError("超限不应保存题目")),
        event_sink=sink,
        max_cost_usd=cap,
        pairer_free=True,
        search_per_thousand_usd=10.0,
        steel_per_scrape_usd=0.0,
        sonnet_price=PRICE,
        clock=lambda: AS_OF,
    )
    result = ask.execute("Python 目前最新稳定版本是哪个？")
    assert isinstance(result, AskStopped)
    assert result.reason == "cost_limit"
    assert extract_called["yes"] is False
    assert "找到 6 个来源" in result.detail
    assert "超过上限" in result.detail
    assert "已停止" in result.detail
    assert result.kept == 6
    rejected = [e for e in sink.events if e.get("type") == "ask_cost_rejected"]
    assert rejected, sink.events
    assert rejected[0].get("sources") == 6
    assert rejected[0]["total_usd"] > cap


def test_go_step8_tokens_new_estimate_covers_actual():
    """第 8 步 Go 真实提问的 token：新估算（6 来源）必须 ≥ 实际花费。"""
    import json
    from pathlib import Path

    from crossfire.config import MODEL_PRICES, WEB_SEARCH_PER_THOUSAND_USD

    fixture = Path(__file__).parent / "fixtures" / "ask_costs" / "go-20261122.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    actual = float(data["ask_cost"]["actual_usd"])
    n = len(data["claims"])
    assert n == 6
    est = estimate_ask_cost(
        pairer_free=True,
        usable_sources=n,
        max_cost_usd=1.0,
        search_per_thousand_usd=WEB_SEARCH_PER_THOUSAND_USD,
        steel_per_scrape_usd=0.0,
        sonnet_price=MODEL_PRICES["claude-sonnet-4-6"],
    )
    assert est.total_usd >= actual, f"estimate {est.total_usd} < actual {actual}"
