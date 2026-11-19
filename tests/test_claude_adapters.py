"""Claude 适配器自己的行为：模型输出按 domain 实体严格转换，批量比对的顺序、回调和并发上限。"""

import re
import threading
import time
from types import SimpleNamespace

import pytest

from crossfire.adapters.anthropic import ClaudeClaimExtractor, ClaudeClaimPairer, ClaudeClient, ClaudeVerdictJudge
from crossfire.adapters.anthropic.judge import JUDGE_PROMPT
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
        usage=Usage(0, 0),
    )


# ---- 结构校验：类型不对必须走失败路径，不许悄悄放行 ----


def test_judge_retries_when_conflicts_come_back_as_a_string():
    client, messages = client_for(scripted({**JUDGMENT, "conflicts": '["时间不同"]'}, JUDGMENT))
    judgment = ClaudeVerdictJudge(client).judge(QUESTION, [], [])

    assert judgment.failure is None
    assert judgment.conflicts == ("时间不同",)
    assert len(messages.prompts) == 2
    assert "conflicts 应为数组" in messages.prompts[1]
    assert judgment.usage == Usage(20, 4)


def test_judge_reports_failure_when_conflicts_stay_a_string(capsys):
    bad = {**JUDGMENT, "conflicts": '["时间不同"]'}
    client, messages = client_for(scripted(bad, bad))
    judgment = ClaudeVerdictJudge(client).judge(QUESTION, [], [])

    assert len(messages.prompts) == 2
    assert judgment.failure is not None
    assert judgment.failure.step == "judge"
    assert "conflicts 应为数组" in judgment.failure.detail
    assert (judgment.answer, judgment.conflicts, judgment.trusted_sources) == (None, (), ())
    assert "❌" in capsys.readouterr().err


def test_judge_rejects_non_string_conflict_items():
    bad = {**JUDGMENT, "conflicts": [{"note": "时间不同"}]}
    client, _ = client_for(scripted(bad, bad))
    assert ClaudeVerdictJudge(client).judge(QUESTION, [], []).failure is not None


def test_pairer_rejects_a_relation_outside_the_enum():
    bad = {"relation": "disagree", "nature": "数字不同"}
    client, messages = client_for(scripted(bad, bad))
    [pair] = ClaudeClaimPairer(client).pair_all(QUESTION, [(claim("https://a.example/", "1"), claim("https://b.example/", "2"))])

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
    result = ClaudeClaimExtractor(client).extract(QUESTION, page, QUESTION.sources[1])

    assert (result.source_url, result.tier, result.text) == ("https://b.example/", Tier.NEWS, "1.0")
    assert result.usage == Usage(10, 2)


def test_extractor_failure_is_an_unanswered_claim_with_failure():
    bad = {"claim": "1.0"}
    client, _ = client_for(scripted(bad, bad))
    page = Page(url="https://a.example/", ok=True, title="t", markdown="正文")
    result = ClaudeClaimExtractor(client).extract(QUESTION, page, QUESTION.sources[0])

    assert result.text is None and result.failure is not None
    assert result.failure.step == "extract"
    assert result.usage == Usage(20, 4)


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
        QUESTION, PAIRS, on_pair=lambda index, total, pair: seen.append((index, total, threading.get_ident()))
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
    ClaudeClaimPairer(client, concurrency=2).pair_all(QUESTION, PAIRS * 3)
    assert peak == 2


def test_pair_all_with_no_pairs_makes_no_calls():
    client, messages = client_for(relation_by_text)
    assert ClaudeClaimPairer(client).pair_all(QUESTION, []) == []
    assert messages.prompts == []


# ---- 关系名只有 Relation 一个来源 ----


def test_pair_schema_and_prompt_take_relation_names_from_the_enum():
    assert PAIR_SCHEMA["properties"]["relation"]["enum"] == [relation.value for relation in Relation]
    assert sorted(RELATION_NAMES.values()) == sorted(relation.value for relation in Relation)
    for name, template in [("PAIR_PROMPT", PAIR_PROMPT), ("JUDGE_PROMPT", JUDGE_PROMPT)]:
        template_text = re.sub(r"\{\w+\}", "", template)
        for relation in Relation:
            assert relation.value not in template_text, f"{relation.value} 在 {name} 模板里被手写了"
