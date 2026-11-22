"""Claude 适配器自己的行为：模型输出按 domain 实体严格转换，批量比对的顺序、回调和并发上限。"""

import re
import threading
import time
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from crossfire.adapters.anthropic import ClaudeClaimExtractor, ClaudeClaimPairer, ClaudeClient, ClaudeVerdictJudge
from crossfire.adapters.anthropic.client import prompt_version
from crossfire.adapters.anthropic.judge import JUDGE_PROMPT, JUDGE_SCHEMA, without_sources_over_memory
from crossfire.adapters.anthropic.pairer import PAIR_PROMPT, PAIR_SCHEMA, RELATION_NAMES
from crossfire.domain import Claim, Page, Question, Relation, Source, Tier, Usage

QUESTION = Question(
    id="q",
    text="当前版本是多少？",
    sources=(
        Source("https://a.example/", Tier.PRIMARY),
        Source("https://b.example/", Tier.NEWS),
        Source("https://c.example/", Tier.AGGREGATOR),
    ),
)

AS_OF = date(2026, 9, 12)

EXTRACTED = {
    "claim": "1.0",
    "evidence": "v1.0",
    "source_type": "news_article",
    "confidence": 0.8,
    "published_date": None,
    "content_date": None,
    "content_date_evidence": None,
}

JUDGMENT = {
    "answer": "1.0",
    "confidence": 0.9,
    "reasoning": "一手源",
    "conflicts": ["时间不同"],
    "trusted_sources": ["https://a.example/"],
}


def tool_message(data, input_tokens=10, output_tokens=2):
    block = SimpleNamespace(type="tool_use", input=data, model_dump=lambda: {"type": "tool_use", "input": data})
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[block],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class FakeMessages:
    """respond(prompt) -> tool 入参 dict。线程安全，供并发的 pairer 使用。"""

    def __init__(self, respond):
        self.respond = respond
        self.prompts = []
        self._lock = threading.Lock()

    def create(self, **kwargs):
        prompt = kwargs["messages"][0]["content"]
        with self._lock:
            self.prompts.append(prompt)
        return tool_message(self.respond(prompt))


def client_for(respond):
    messages = FakeMessages(respond)
    return ClaudeClient(client=SimpleNamespace(messages=messages), sleep=lambda delay: None), messages


def scripted(*responses):
    queue = list(responses)
    return lambda prompt: queue.pop(0)


def claim(url, text, tier=Tier.PRIMARY):
    return Claim(
        source_url=url,
        tier=tier,
        text=text,
        evidence=None,
        source_type=None,
        published_date=None,
        confidence=0.9,
        usage=Usage(0, 0, 0),
    )


# ---- 结构校验：类型不对必须走失败路径，不许悄悄放行 ----


def test_judge_retries_when_conflicts_come_back_as_a_string():
    client, messages = client_for(scripted({**JUDGMENT, "conflicts": '["时间不同"]'}, JUDGMENT))
    judgment = ClaudeVerdictJudge(client).judge(QUESTION, [], [], AS_OF)

    assert judgment.failure is None
    assert judgment.conflicts == ("时间不同",)
    assert len(messages.prompts) == 2
    assert "conflicts 应为数组" in messages.prompts[1]
    # 第 3 步有意修改：Usage(输入, 输出) → Usage(输入, 输出, 请求数)，原因：backlog「claude_calls 少算重试」
    assert judgment.usage == Usage(20, 4, 2)


def test_judge_reports_failure_when_conflicts_stay_a_string(capsys):
    bad = {**JUDGMENT, "conflicts": '["时间不同"]'}
    client, messages = client_for(scripted(bad, bad))
    judgment = ClaudeVerdictJudge(client).judge(QUESTION, [], [], AS_OF)

    assert len(messages.prompts) == 2
    assert judgment.failure is not None
    assert judgment.failure.step == "judge"
    assert "conflicts 应为数组" in judgment.failure.detail
    assert (judgment.answer, judgment.conflicts, judgment.trusted_sources) == (None, (), ())
    assert "❌" in capsys.readouterr().err


def test_judge_rejects_non_string_conflict_items():
    bad = {**JUDGMENT, "conflicts": [{"note": "时间不同"}]}
    client, _ = client_for(scripted(bad, bad))
    assert ClaudeVerdictJudge(client).judge(QUESTION, [], [], AS_OF).failure is not None


def test_pairer_rejects_a_relation_outside_the_enum():
    bad = {"relation": "disagree", "nature": "数字不同"}
    client, messages = client_for(scripted(bad, bad))
    [pair] = ClaudeClaimPairer(client).pair_all(QUESTION, [(claim("https://a.example/", "1"), claim("https://b.example/", "2"))], AS_OF)

    assert len(messages.prompts) == 2
    assert pair.relation is None
    assert pair.failure is not None and "disagree" in pair.failure.detail


def test_extractor_keeps_the_page_url_and_source_tier_even_if_the_model_echoes_others():
    data = {
        "claim": "1.0",
        "evidence": "v1.0",
        "source_type": "news_article",
        "confidence": 0.8,
        "published_date": None,
        "url": "https://elsewhere.example/",
        "tier": "primary",
    }
    client, _ = client_for(scripted(data))
    page = Page(url="https://b.example/", ok=True, title="t", markdown="正文")
    result = ClaudeClaimExtractor(client).extract(QUESTION, page, AS_OF)

    assert (result.source_url, result.tier, result.text) == ("https://b.example/", Tier.NEWS, "1.0")
    # 第 3 步有意修改：Usage(输入, 输出) → Usage(输入, 输出, 请求数)，原因：backlog「claude_calls 少算重试」
    assert result.usage == Usage(10, 2, 1)


def test_extractor_failure_is_an_unanswered_claim_with_failure():
    bad = {"claim": "1.0"}
    client, _ = client_for(scripted(bad, bad))
    page = Page(url="https://a.example/", ok=True, title="t", markdown="正文")
    result = ClaudeClaimExtractor(client).extract(QUESTION, page, AS_OF)

    assert result.text is None and result.failure is not None
    assert result.failure.step == "extract"
    # 第 3 步有意修改：Usage(输入, 输出) → Usage(输入, 输出, 请求数)，原因：backlog「claude_calls 少算重试」
    assert result.usage == Usage(20, 4, 2)


# ---- 批量比对 ----

PAIRS = [
    (claim("https://a.example/", "1"), claim("https://b.example/", "1")),
    (claim("https://a.example/", "1"), claim("https://c.example/", "2")),
    (claim("https://b.example/", "1"), claim("https://c.example/", "2")),
]


def relation_by_text(prompt):
    a_claim = prompt.split("主张: ")[1].split("\n")[0]
    b_claim = prompt.split("主张: ")[2].split("\n")[0]
    return {"relation": "agree" if a_claim == b_claim else "contradict", "nature": "测试"}


def test_pair_all_returns_results_in_input_order_and_reports_each_once():
    client, _ = client_for(relation_by_text)
    seen = []
    caller = threading.get_ident()
    pairs = ClaudeClaimPairer(client).pair_all(
        QUESTION, PAIRS, AS_OF, on_pair=lambda index, total, pair: seen.append((index, total, threading.get_ident()))
    )

    assert [(p.a_url, p.b_url) for p in pairs] == [(a.source_url, b.source_url) for a, b in PAIRS]
    assert [p.relation for p in pairs] == [Relation.AGREE, Relation.CONTRADICT, Relation.CONTRADICT]
    assert sorted(index for index, _, _ in seen) == [0, 1, 2]
    assert {total for _, total, _ in seen} == {3}
    assert {thread for _, _, thread in seen} == {caller}, "on_pair 必须在调用方线程里触发"


def test_pair_all_never_exceeds_its_concurrency():
    active = 0
    peak = 0
    lock = threading.Lock()

    def slow(prompt):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return {"relation": "agree", "nature": "测试"}

    client, _ = client_for(slow)
    ClaudeClaimPairer(client, concurrency=2).pair_all(QUESTION, PAIRS * 3, AS_OF)
    assert peak == 2


def test_pair_all_turns_exceptions_into_failed_pairs_instead_of_raising(capsys):
    """端口约定：比对阶段抛异常会让已经花钱做完的抓取和提取全部作废，所以失败只能记在 Pair 上。"""

    def flaky(prompt):
        if "主张: 2" in prompt:
            raise anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.invalid/"))
        return {"relation": "agree", "nature": "测试"}

    client, _ = client_for(flaky)
    seen = []
    pairs = ClaudeClaimPairer(client).pair_all(QUESTION, PAIRS, AS_OF, on_pair=lambda index, total, pair: seen.append(index))

    assert [p.failure is None for p in pairs] == [True, False, False]
    assert [p.relation for p in pairs] == [Relation.AGREE, None, None]
    assert pairs[1].failure is not None
    assert pairs[1].failure.step == "pair"
    assert "APITimeoutError" in pairs[1].failure.detail
    assert sorted(seen) == [0, 1, 2]
    assert "❌" in capsys.readouterr().err
    # 网络重试用尽：一次原始请求加两次重试，都算。backlog「比对抛异常时请求数记成 0」。
    assert pairs[1].usage.requests == 3


def test_pair_all_records_unknown_requests_when_something_other_than_the_api_raises():
    def broken(prompt):
        raise RuntimeError("bug")

    client, _ = client_for(broken)
    [pair] = ClaudeClaimPairer(client).pair_all(QUESTION, PAIRS[:1], AS_OF)
    assert pair.failure is not None and "RuntimeError" in pair.failure.detail
    assert pair.usage.requests is None


def test_pair_all_with_no_pairs_makes_no_calls():
    client, messages = client_for(relation_by_text)
    assert ClaudeClaimPairer(client).pair_all(QUESTION, [], AS_OF) == []
    assert messages.prompts == []


# ---- 批量提取 ----

PAGES = [Page(url=s.url, ok=True, title="t", markdown=f"正文 {s.url}") for s in QUESTION.sources]


def claim_for_page(prompt):
    url = prompt.split("网页 URL：")[1].split("\n")[0]
    return {**EXTRACTED, "claim": f"{url} 的主张"}


def test_extract_all_returns_claims_in_page_order_and_reports_each_with_its_page_index():
    """后面的页面先完成：on_claim 的 index 必须是页面下标，不是完成先后。"""

    def slow_first(prompt):
        if PAGES[0].url in prompt:
            time.sleep(0.05)
        return claim_for_page(prompt)

    client, _ = client_for(slow_first)
    seen = []
    caller = threading.get_ident()
    claims = ClaudeClaimExtractor(client, concurrency=3).extract_all(
        QUESTION, PAGES, AS_OF, on_claim=lambda index, claim: seen.append((index, claim.source_url, threading.get_ident()))
    )

    assert [c.source_url for c in claims] == [p.url for p in PAGES]
    assert all(c.text == f"{c.source_url} 的主张" for c in claims)
    assert seen[-1][0] == 0, "最慢的第 0 页应该最后完成"
    assert all(url == PAGES[index].url for index, url, _ in seen)
    assert {thread for _, _, thread in seen} == {caller}, "on_claim 必须在调用方线程里触发"


def test_extract_all_never_exceeds_its_concurrency():
    active = 0
    peak = 0
    lock = threading.Lock()

    def slow(prompt):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return EXTRACTED

    client, _ = client_for(slow)
    ClaudeClaimExtractor(client, concurrency=2).extract_all(QUESTION, PAGES * 3, AS_OF)
    assert peak == 2


def test_extract_all_turns_an_api_error_into_a_failed_claim_with_the_requests_it_spent(capsys):
    def flaky(prompt):
        if PAGES[1].url in prompt:
            raise anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.invalid/"))
        return EXTRACTED

    client, _ = client_for(flaky)
    seen = []
    claims = ClaudeClaimExtractor(client).extract_all(QUESTION, PAGES, AS_OF, on_claim=lambda i, c: seen.append(i))

    assert [c.failure is None for c in claims] == [True, False, True]
    failed = claims[1]
    assert failed.text is None and failed.tier is Tier.NEWS
    assert failed.failure is not None and failed.failure.step == "extract" and "APITimeoutError" in failed.failure.detail
    assert failed.usage.requests == 3
    assert sorted(seen) == [0, 1, 2]
    assert "❌" in capsys.readouterr().err


def test_extract_all_marks_every_page_failed_when_the_whole_batch_fails():
    def down(prompt):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.invalid/"))

    client, _ = client_for(down)
    seen = []
    claims = ClaudeClaimExtractor(client).extract_all(QUESTION, PAGES, AS_OF, on_claim=lambda i, c: seen.append(i))
    assert [c.source_url for c in claims] == [p.url for p in PAGES]
    assert all(c.failure is not None and c.usage.requests == 3 for c in claims)
    assert sorted(seen) == [0, 1, 2]


def test_extract_all_with_no_pages_makes_no_calls():
    client, messages = client_for(claim_for_page)
    assert ClaudeClaimExtractor(client).extract_all(QUESTION, [], AS_OF) == []
    assert messages.prompts == []


# ---- 关系名只有 Relation 一个来源 ----


def test_pair_schema_and_prompt_take_relation_names_from_the_enum():
    assert PAIR_SCHEMA["properties"]["relation"]["enum"] == [relation.value for relation in Relation]
    assert sorted(RELATION_NAMES.values()) == sorted(relation.value for relation in Relation)
    for name, template in [("PAIR_PROMPT", PAIR_PROMPT), ("JUDGE_PROMPT", JUDGE_PROMPT)]:
        template_text = re.sub(r"\{\w+\}", "", template)
        for relation in Relation:
            assert relation.value not in template_text, f"{relation.value} 在 {name} 模板里被手写了"


# ---- 第 5a 步：告诉模型「今天」是哪天，记下模型和 prompt 版本 ----

@pytest.mark.parametrize("as_of", [date(2026, 9, 12), date(2031, 1, 2)])
def test_every_prompt_carries_the_date_it_was_given_not_today(as_of):
    client, messages = client_for(scripted(EXTRACTED, {"relation": "agree", "nature": "测试"}, JUDGMENT))
    page = Page(url="https://a.example/", ok=True, title="t", markdown="正文")
    ClaudeClaimExtractor(client).extract(QUESTION, page, as_of)
    ClaudeClaimPairer(client).pair_all(QUESTION, PAIRS[:1], as_of)
    ClaudeVerdictJudge(client).judge(QUESTION, [], [], as_of)
    assert [f"今天的日期：{as_of.isoformat()}" in prompt for prompt in messages.prompts] == [True, True, True]


def test_pair_prompt_shows_both_publication_dates_and_says_when_one_is_missing():
    # 第 7b 步有意修改：prompt 改成「页面发布日 / 内容所述时间」两行。
    client, messages = client_for(scripted({"relation": "contradict", "nature": "时间不同"}))
    dated = replace(
        claim("https://a.example/", "最新是 3.13"),
        published_date="2024-10-07",
        content_date="2024-10-01",
    )
    undated = claim("https://b.example/", "最新是 3.15.2")
    ClaudeClaimPairer(client).pair_all(QUESTION, [(dated, undated)], AS_OF)
    [prompt] = messages.prompts
    assert "页面发布日: 2024-10-07" in prompt
    assert "内容所述时间: 2024-10-01" in prompt
    assert "页面发布日: 未知" in prompt and "内容所述时间: 未知" in prompt
    assert "None" not in prompt


def test_provenance_names_the_model_and_a_version_of_each_prompt():
    def adapters(model):
        client = ClaudeClient(client=SimpleNamespace(messages=None), model=model)
        return ClaudeClaimExtractor(client), ClaudeClaimPairer(client), ClaudeVerdictJudge(client)

    first, again, other_model = adapters("m-1"), adapters("m-1"), adapters("m-2")
    versions = [adapter.provenance.prompt_version for adapter in first]
    assert all(adapter.provenance.model == "m-1" for adapter in first)
    assert len(set(versions)) == 3 and all(re.fullmatch(r"[0-9a-f]{12}", v or "") for v in versions)
    assert [a.provenance for a in first] == [a.provenance for a in again]
    assert [a.provenance.prompt_version for a in other_model] == versions


def test_prompt_version_changes_with_the_template_or_the_schema():
    assert prompt_version("a", {}) == prompt_version("a", {})
    assert prompt_version("a", {}) != prompt_version("b", {})
    assert prompt_version("a", {}) != prompt_version("a", {"type": "object"})


def test_dropping_the_sources_over_memory_block_removes_only_that_block():
    trimmed = without_sources_over_memory()
    assert "关于你自己的知识" not in trimmed and "一手来源（primary）明确写出的事实" not in trimmed
    assert JUDGE_PROMPT.replace(JUDGE_PROMPT[JUDGE_PROMPT.index("关于你自己的知识"):JUDGE_PROMPT.index("判断原则，按优先级")], "") == trimmed
    client = ClaudeClient(client=SimpleNamespace(messages=None), model="m")
    assert ClaudeVerdictJudge(client).provenance.prompt_version == prompt_version(JUDGE_PROMPT, JUDGE_SCHEMA)
    assert ClaudeVerdictJudge(client, trimmed).provenance != ClaudeVerdictJudge(client).provenance


def test_judge_sends_the_prompt_it_was_given():
    client, messages = client_for(scripted(JUDGMENT))
    ClaudeVerdictJudge(client, without_sources_over_memory()).judge(QUESTION, [], [], AS_OF)
    assert "关于你自己的知识" not in messages.prompts[0] and "今天的日期：2026-09-12" in messages.prompts[0]
