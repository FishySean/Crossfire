"""事件类型的 to_dict 必须与第 0 步锁住的事件形状逐键一致，连顺序也一样。"""

import pytest

from crossfire.application.events import (
    ClaimDone,
    Done,
    Error,
    FetchDone,
    Heartbeat,
    JudgeStart,
    PairDone,
    PairStart,
    Start,
)
from crossfire.domain import Judgment, Usage
from tests.test_pipeline_contract import EVENT_FIELDS

JUDGMENT = Judgment("1.0", 0.9, "一手源", (), ("https://a.example/",), Usage(10, 2, 1))

# 键的顺序照着改造前 pipeline.run 里各个 dict 字面量的写法手抄，不要改成从代码里反推。
EXPECTED = [
    (Start("问题", 4), ["type", "question", "total_sources"]),
    (FetchDone("https://a.example/", True, 120, 0), ["type", "url", "ok", "chars", "index"]),
    (ClaimDone("https://a.example/", "1.0", "primary", 0), ["type", "url", "claim", "tier", "index"]),
    (PairStart(6), ["type", "total_pairs"]),
    (
        PairDone("https://a.example/", "https://b.example/", "agree", "粒度不同", 0, 6),
        ["type", "a_url", "b_url", "relation", "nature", "index", "total"],
    ),
    (JudgeStart(), ["type"]),
    (Heartbeat("judge", 5.0), ["type", "step", "elapsed"]),
    (Done(JUDGMENT, "out/runs/q.json", 12.5), ["type", "judgment", "run_file", "elapsed"]),
    (Error("fetch", "503"), ["type", "step", "detail"]),
]


@pytest.mark.parametrize(("event", "keys"), EXPECTED, ids=[event.type for event, _ in EXPECTED])
def test_event_keys_and_order_match_the_contract(event, keys):
    data = event.to_dict()
    assert list(data) == keys
    assert set(data) == EVENT_FIELDS[data["type"]]


def test_every_event_type_in_the_contract_has_a_class():
    assert {event.type for event, _ in EXPECTED} == set(EVENT_FIELDS)


def test_done_carries_the_judgment_as_a_plain_dict():
    data = Done(JUDGMENT, "out/runs/q.json", 12.5).to_dict()
    assert data["judgment"] == JUDGMENT.to_dict()
    assert data == {"type": "done", "judgment": JUDGMENT.to_dict(), "run_file": "out/runs/q.json", "elapsed": 12.5}


def test_values_are_passed_through_unchanged():
    assert PairDone("a", "b", None, None, 3, 6).to_dict() == {
        "type": "pair_done",
        "a_url": "a",
        "b_url": "b",
        "relation": None,
        "nature": None,
        "index": 3,
        "total": 6,
    }
