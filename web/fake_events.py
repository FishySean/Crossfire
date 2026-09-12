"""Scripted progress events for developing and rehearsing the live view.

The real stream comes from the pipeline's /api/run/{question_id}; these scenarios
emit the exact same event shapes so the frontend can be exercised (and demoed)
without the pipeline, and so odd orderings can be reproduced on demand.
"""

from itertools import combinations

SCENARIOS = ("normal", "shuffled", "with-error", "stall")

QUESTION = "What is the latest stable version of Python?"

SOURCES = [
    {
        "url": "https://www.python.org/downloads/",
        "tier": "primary",
        "chars": 15861,
        "claim": "The latest stable release is Python 3.13.1.",
    },
    {
        "url": "https://devguide.python.org/versions/",
        "tier": "primary",
        "chars": 7719,
        "claim": "Python 3.13 is the current bugfix release; 3.14 is in development.",
    },
    {
        "url": "https://realpython.com/python313-new-features/",
        "tier": "news",
        "chars": 62947,
        "claim": "Python 3.13 is the newest version and ships a new REPL.",
    },
    {
        "url": "https://www.w3schools.com/python/python_intro.asp",
        "tier": "aggregator",
        "chars": 32393,
        "claim": "The latest major version is Python 3.11.",
    },
]

CONTRADICTS = {
    ("https://www.w3schools.com/python/python_intro.asp", "https://www.python.org/downloads/"):
        "One says 3.13.1 is current, the other still says 3.11.",
    ("https://www.w3schools.com/python/python_intro.asp", "https://devguide.python.org/versions/"):
        "3.11 vs 3.13 as the current release line.",
    ("https://www.w3schools.com/python/python_intro.asp", "https://realpython.com/python313-new-features/"):
        "3.11 vs 3.13 as the newest version.",
}

JUDGMENT = {
    "answer": "Python 3.13 is the latest stable release (3.13.1 at the time of the run).",
    "confidence": 0.86,
    "reasoning": (
        "Both primary sources (python.org and the developer guide) agree on the 3.13 line. "
        "The w3schools page still names 3.11 and is an aggregator with no publication date, "
        "so it is treated as stale rather than as a competing claim."
    ),
    "conflicts": ["w3schools reports 3.11 while python.org reports 3.13.1"],
    "trusted_sources": [
        "https://www.python.org/downloads/",
        "https://devguide.python.org/versions/",
    ],
}


def _pairs():
    return list(combinations([source["url"] for source in SOURCES], 2))


def _relation(a, b):
    nature = CONTRADICTS.get((a, b)) or CONTRADICTS.get((b, a))
    if nature:
        return "contradict", nature
    return "agree", "Both point at the 3.13 release line."


def _base_events(*, error_steps=()):
    """(delay_before_event, event) pairs for one scripted run."""
    pairs = _pairs()
    events = [(0.0, {"type": "start", "question": QUESTION, "total_sources": len(SOURCES)})]

    for index, source in enumerate(SOURCES):
        if "fetch" in error_steps and index == 2:
            events.append((0.45, {"type": "error", "step": "fetch", "detail": f"Steel 429 on {source['url']}"}))
            events.append((0.05, {"type": "fetch_done", "url": source["url"], "ok": False, "chars": 0, "index": index}))
            continue
        events.append(
            (0.45, {"type": "fetch_done", "url": source["url"], "ok": True, "chars": source["chars"], "index": index})
        )

    for index, source in enumerate(SOURCES):
        if "fetch" in error_steps and index == 2:
            events.append((0.3, {"type": "claim_done", "url": source["url"], "claim": None, "tier": source["tier"], "index": index}))
            continue
        events.append(
            (
                0.35,
                {
                    "type": "claim_done",
                    "url": source["url"],
                    "claim": source["claim"],
                    "tier": source["tier"],
                    "index": index,
                },
            )
        )

    events.append((0.3, {"type": "pair_start", "total_pairs": len(pairs)}))
    for index, (a, b) in enumerate(pairs):
        if "pair" in error_steps and index == 1:
            events.append((0.3, {"type": "error", "step": "pair", "detail": f"model response was not valid JSON for {a} / {b}"}))
            events.append(
                (0.05, {"type": "pair_done", "a_url": a, "b_url": b, "relation": None, "nature": "", "index": index, "total": len(pairs)})
            )
            continue
        relation, nature = _relation(a, b)
        events.append(
            (
                0.3,
                {
                    "type": "pair_done",
                    "a_url": a,
                    "b_url": b,
                    "relation": relation,
                    "nature": nature,
                    "index": index,
                    "total": len(pairs),
                },
            )
        )

    events.append((0.4, {"type": "judge_start"}))
    events.append(
        (
            1.2,
            {
                "type": "done",
                "judgment": JUDGMENT,
                "run_file": "out/runs/python-latest-version_fake.json",
                "elapsed": 8.4,
            },
        )
    )
    return events


def _shuffle_pair_events(events):
    """Deliver pair_done events out of order, keeping their index field intact."""
    pair_indices = [i for i, (_, event) in enumerate(events) if event["type"] == "pair_done"]
    payloads = [events[i] for i in pair_indices]
    reordered = payloads[::-1]
    reordered[0], reordered[1] = reordered[1], reordered[0]
    for slot, item in zip(pair_indices, reordered, strict=True):
        events[slot] = item
    return events


def scenario_events(scenario):
    if scenario == "stall":
        return []
    if scenario == "with-error":
        return _base_events(error_steps=("fetch", "pair"))
    if scenario == "shuffled":
        return _shuffle_pair_events(_base_events())
    return _base_events()
