"""Scripted progress events for developing and rehearsing the live view.

The real stream comes from the pipeline's /api/run/{question_id}; these scenarios
emit the exact same event shapes so the frontend can be exercised (and demoed)
without the pipeline, and so odd orderings can be reproduced on demand.
"""

from itertools import combinations

SCENARIOS = ("normal", "shuffled", "with-error", "stall", "scope", "dense")

# The real judge step is one long call that emits nothing else for 15-27s, so the
# scripted runs reproduce that gap along with the heartbeats that keep the
# frontend's stall warning from firing in the middle of it.
JUDGE_SECONDS = 17.0
HEARTBEAT_SECONDS = 5.0

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


# Tokyo population: every source is right, they just count different areas. Two
# of them do disagree outright, and one source fails to fetch, so claim indices
# skip a slot the way the real pipeline's do.
SCOPE_QUESTION = "What is the population of Tokyo?"

SCOPE_SOURCES = [
    {
        "url": "https://www.metro.tokyo.lg.jp/english/about/statistics.html",
        "tier": "primary",
        "chars": 9214,
        "claim": "Tokyo Metropolis has about 14.2 million residents.",
    },
    {
        "url": "https://www.stat.go.jp/english/data/handbook/c0117.html",
        "tier": "primary",
        "chars": 0,
        "claim": None,
        "fetch_ok": False,
    },
    {
        "url": "https://en.wikipedia.org/wiki/Greater_Tokyo_Area",
        "tier": "aggregator",
        "chars": 48120,
        "claim": "The Greater Tokyo Area is home to roughly 37 million people.",
    },
    {
        "url": "https://www.citypopulation.de/en/japan/tokyo/",
        "tier": "aggregator",
        "chars": 12608,
        "claim": "Tokyo's 23 special wards hold about 9.7 million people.",
    },
]

SCOPE_RELATIONS = {
    (
        "https://www.metro.tokyo.lg.jp/english/about/statistics.html",
        "https://en.wikipedia.org/wiki/Greater_Tokyo_Area",
    ): (
        "same_question_different_scope",
        "14.2M counts the prefecture, 37M counts the whole metropolitan area — both are correct.",
    ),
    (
        "https://www.metro.tokyo.lg.jp/english/about/statistics.html",
        "https://www.citypopulation.de/en/japan/tokyo/",
    ): (
        "same_question_different_scope",
        "Prefecture (14.2M) versus the 23 special wards (9.7M).",
    ),
    (
        "https://en.wikipedia.org/wiki/Greater_Tokyo_Area",
        "https://www.citypopulation.de/en/japan/tokyo/",
    ): (
        "contradict",
        "Both are presented as 'Tokyo' with no boundary given, and 37M cannot also be 9.7M.",
    ),
}

SCOPE_JUDGMENT = {
    "answer": "It depends on the boundary: 9.7M in the 23 wards, 14.2M in Tokyo Metropolis, ~37M in Greater Tokyo.",
    "confidence": 0.79,
    "reasoning": (
        "The sources are not in conflict about the facts — they report different administrative "
        "boundaries. Only the two aggregator pages, which both say 'Tokyo' without naming a boundary, "
        "are genuinely incompatible with each other."
    ),
    "conflicts": ["Greater Tokyo (37M) and the 23 wards (9.7M) are both labelled simply 'Tokyo'"],
    "trusted_sources": ["https://www.metro.tokyo.lg.jp/english/about/statistics.html"],
}


def _pairs(sources):
    return list(combinations([source["url"] for source in sources], 2))


def _relation(a, b):
    nature = CONTRADICTS.get((a, b)) or CONTRADICTS.get((b, a))
    if nature:
        return "contradict", nature
    return "agree", "Both point at the 3.13 release line."


def _scope_relation(a, b):
    found = SCOPE_RELATIONS.get((a, b)) or SCOPE_RELATIONS.get((b, a))
    return found or ("unrelated", "The failed source makes no claim to compare.")


# The worst case the demo can hit: seven sources means 21 pairs, and almost all
# of them are scope differences, so the conflict panel has to stay readable with
# 17 orange links crossing the source grid at once.
DENSE_QUESTION = "How many people live in Tokyo?"

DENSE_SOURCES = [
    {
        "url": "https://www.metro.tokyo.lg.jp/english/about/statistics.html",
        "tier": "primary",
        "chars": 9214,
        "claim": "Tokyo Metropolis has about 14.2 million residents.",
    },
    {
        "url": "https://www.stat.go.jp/english/data/jinsui/index.html",
        "tier": "primary",
        "chars": 6480,
        "claim": "The Tokyo prefecture population estimate is 14,183,000.",
    },
    {
        "url": "https://en.wikipedia.org/wiki/Greater_Tokyo_Area",
        "tier": "aggregator",
        "chars": 48120,
        "claim": "The Greater Tokyo Area is home to roughly 37 million people.",
    },
    {
        "url": "https://www.citypopulation.de/en/japan/tokyo/",
        "tier": "aggregator",
        "chars": 12608,
        "claim": "Tokyo's 23 special wards hold about 9.7 million people.",
    },
    {
        "url": "https://worldpopulationreview.com/world-cities/tokyo-population",
        "tier": "aggregator",
        "chars": 8102,
        "claim": "Tokyo's population is 37.4 million.",
    },
    {
        "url": "https://www.macrotrends.net/cities/21671/tokyo/population",
        "tier": "aggregator",
        "chars": 5321,
        "claim": "The Tokyo metro area population is 37,115,000.",
    },
    {
        "url": "https://www.bbc.com/news/world-asia-tokyo-population",
        "tier": "news",
        "chars": 14770,
        "claim": "Tokyo's daytime population swells to 16.4 million on a working day.",
    },
]

# Sources grouped by what they actually measure; pairs across groups are scope
# differences, and two same-scope pairs really do disagree.
DENSE_SCOPES = {
    0: "prefecture",
    1: "prefecture",
    2: "metro area",
    3: "23 wards",
    4: "metro area",
    5: "metro area",
    6: "daytime population",
}

DENSE_CONTRADICTS = {
    (2, 4): "Both say 'Greater Tokyo' but give roughly 37M and 37.4M with no year attached.",
    (4, 5): "Same metro area, same year: 37.4M against 37,115,000.",
}

DENSE_JUDGMENT = {
    "answer": "9.7M in the 23 wards, 14.2M in Tokyo Metropolis, ~37M in the Greater Tokyo Area.",
    "confidence": 0.81,
    "reasoning": (
        "Seventeen of the twenty-one pairs disagree only because they measure different "
        "boundaries, which is why the raw numbers range from 9.7M to 37.4M. Only two pairs "
        "use the same boundary and still disagree, and both of those involve the same "
        "aggregator's 37.4M figure."
    ),
    "conflicts": [
        "37.4M against roughly 37M for the same metro area",
        "37.4M against 37,115,000 for the same metro area and year",
    ],
    "trusted_sources": [
        "https://www.metro.tokyo.lg.jp/english/about/statistics.html",
        "https://www.stat.go.jp/english/data/jinsui/index.html",
    ],
}


def _dense_relation(a, b):
    ia = next(i for i, s in enumerate(DENSE_SOURCES) if s["url"] == a)
    ib = next(i for i, s in enumerate(DENSE_SOURCES) if s["url"] == b)
    nature = DENSE_CONTRADICTS.get((ia, ib)) or DENSE_CONTRADICTS.get((ib, ia))
    if nature:
        return "contradict", nature
    if DENSE_SCOPES[ia] != DENSE_SCOPES[ib]:
        return (
            "same_question_different_scope",
            f"One counts the {DENSE_SCOPES[ia]}, the other the {DENSE_SCOPES[ib]} — both are correct.",
        )
    return "agree", f"Both report the {DENSE_SCOPES[ia]} and land on the same figure."


def _run_events(*, question, sources, relation_of, judgment, run_file, elapsed):
    """Events for one scripted run over the given sources.

    A source with fetch_ok False emits no claim_done at all, so claim indices
    skip a slot — the shape that catches a claim index based on claim order
    instead of source order.
    """
    pairs = _pairs(sources)
    events = [(0.0, {"type": "start", "question": question, "total_sources": len(sources)})]

    for index, source in enumerate(sources):
        ok = source.get("fetch_ok", True)
        if not ok:
            events.append((0.4, {"type": "error", "step": "fetch", "detail": f"timeout after 30s on {source['url']}"}))
        events.append(
            (
                0.05 if not ok else 0.45,
                {"type": "fetch_done", "url": source["url"], "ok": ok, "chars": source["chars"], "index": index},
            )
        )

    for index, source in enumerate(sources):
        if not source.get("fetch_ok", True):
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
        relation, nature = relation_of(a, b)
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

    events.extend(_judge_events(judgment=judgment, run_file=run_file, elapsed=elapsed))
    return events


def _judge_events(*, judgment, run_file, elapsed):
    """judge_start, a heartbeat every HEARTBEAT_SECONDS, then done."""
    events = [(0.4, {"type": "judge_start"})]
    beats = int(JUDGE_SECONDS // HEARTBEAT_SECONDS)
    for beat in range(1, beats + 1):
        events.append(
            (
                HEARTBEAT_SECONDS,
                {"type": "heartbeat", "step": "judge", "elapsed": round(beat * HEARTBEAT_SECONDS, 1)},
            )
        )
    events.append(
        (
            JUDGE_SECONDS - beats * HEARTBEAT_SECONDS,
            {"type": "done", "judgment": judgment, "run_file": run_file, "elapsed": elapsed},
        )
    )
    return events


def _base_events(*, error_steps=()):
    """(delay_before_event, event) pairs for one scripted run."""
    pairs = _pairs(SOURCES)
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

    events.extend(
        _judge_events(
            judgment=JUDGMENT,
            run_file="out/runs/python-latest-version_fake.json",
            elapsed=8.4,
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
    if scenario == "scope":
        return _run_events(
            question=SCOPE_QUESTION,
            sources=SCOPE_SOURCES,
            relation_of=_scope_relation,
            judgment=SCOPE_JUDGMENT,
            run_file="out/runs/tokyo-population_fake.json",
            elapsed=9.1,
        )
    if scenario == "dense":
        return _run_events(
            question=DENSE_QUESTION,
            sources=DENSE_SOURCES,
            relation_of=_dense_relation,
            judgment=DENSE_JUDGMENT,
            run_file="out/runs/tokyo-population-dense_fake.json",
            elapsed=21.6,
        )
    if scenario == "with-error":
        return _base_events(error_steps=("fetch", "pair"))
    if scenario == "shuffled":
        return _shuffle_pair_events(_base_events())
    return _base_events()
