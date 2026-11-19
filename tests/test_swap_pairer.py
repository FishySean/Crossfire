"""接入自训 NLI 模型的演练：换一个与 Claude 无关的 pairer，业务代码一行不改就能跑通。"""

import socket

import pytest

import crossfire.pipeline as pipeline
from crossfire.domain import Question
from tests.fakes import CallLog, EqualityPairer, FakeExtractor, FakeFetcher, FakeJudge

SOURCES = [
    {"url": "https://a.example/", "tier": "primary"},
    {"url": "https://b.example/", "tier": "news"},
    {"url": "https://c.example/", "tier": "aggregator"},
    {"url": "https://d.example/", "tier": "aggregator"},
]
QUESTION = Question.from_dict({"id": "swap-pairer", "question": "当前版本是多少？", "sources": SOURCES})
TEXTS = {
    "https://a.example/": "1.0",
    "https://b.example/": "1.0",
    "https://c.example/": "0.9",
    "https://d.example/": "1.0",
}


def _refuse(*args, **kwargs):
    raise AssertionError("测试里不允许任何真实网络调用")


def test_equality_pairer_runs_the_whole_pipeline(monkeypatch, tmp_path):
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(pipeline, "RUNS_DIR", tmp_path)
    log = CallLog()
    pairer = EqualityPairer()
    events = []

    result = pipeline.run(
        QUESTION,
        fetcher=FakeFetcher(),
        extractor=FakeExtractor(log, texts=TEXTS),
        pairer=pairer,
        judge=FakeJudge(log, trusted_url="https://a.example/"),
        on_event=events.append,
    )

    assert pairer.batches == [6], "整批一次交给 pairer，而不是一对一对地调用"
    relations = {frozenset((p["a"], p["b"])): p["relation"] for p in result["pairs"]}
    assert relations[frozenset(("https://a.example/", "https://b.example/"))] == "agree"
    assert relations[frozenset(("https://a.example/", "https://c.example/"))] == "contradict"
    assert sorted(relations.values()) == ["agree"] * 3 + ["contradict"] * 3
    assert [e["relation"] for e in events if e["type"] == "pair_done"] == [p["relation"] for p in result["pairs"]]
    assert events[-1]["type"] == "done"
    assert result["failures"] == []


@pytest.mark.parametrize("answered", [0, 1])
def test_pairer_gets_an_empty_batch_when_fewer_than_two_claims(monkeypatch, tmp_path, answered):
    monkeypatch.setattr(pipeline, "RUNS_DIR", tmp_path)
    log = CallLog()
    pairer = EqualityPairer()
    failing = [s["url"] for s in SOURCES][answered:]

    result = pipeline.run(
        QUESTION,
        fetcher=FakeFetcher(failing_urls=failing),
        extractor=FakeExtractor(log, texts=TEXTS),
        pairer=pairer,
        judge=FakeJudge(log, trusted_url="https://a.example/"),
    )

    assert pairer.batches == [0]
    assert result["pairs"] == []
