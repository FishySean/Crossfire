"""Offline checks for is_usable_page. Fixtures are captured once by
scripts/capture_page_fixtures.py; these tests never hit the network."""

import json
from pathlib import Path

import pytest
import yaml

from crossfire.steel_client import (
    UNUSABLE_EMPTY,
    UNUSABLE_ERROR_TITLE,
    UNUSABLE_FETCH_FAILED,
    UNUSABLE_NAV_SKELETON,
    UNUSABLE_TOO_SHORT,
    _shape,
    is_usable_page,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pages"
QUESTIONS = Path(__file__).resolve().parents[1] / "questions" / "demo.yaml"

KNOWN_BAD = {
    "bad_britannica_softblock": UNUSABLE_TOO_SHORT,
    "bad_thenewstack_page_not_found": UNUSABLE_ERROR_TITLE,
    "bad_theregister_404_title": UNUSABLE_ERROR_TITLE,
    "bad_space_nav_skeleton": UNUSABLE_NAV_SKELETON,
}


def load(name):
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def good_fixtures():
    return sorted(FIXTURE_DIR.glob("good_*.json"))


@pytest.mark.parametrize(("name", "reason"), sorted(KNOWN_BAD.items()))
def test_known_bad_pages_are_unusable(name, reason):
    usable, actual = is_usable_page(load(name))
    assert not usable
    assert actual == reason


def test_bad_reasons_distinguish_the_failure_modes():
    reasons = {name: is_usable_page(load(name))[1] for name in KNOWN_BAD}
    assert reasons["bad_britannica_softblock"] != reasons["bad_space_nav_skeleton"]
    assert reasons["bad_thenewstack_page_not_found"] != reasons["bad_space_nav_skeleton"]


@pytest.mark.parametrize("path", good_fixtures(), ids=lambda p: p.stem)
def test_demo_sources_are_usable(path):
    result = json.loads(path.read_text(encoding="utf-8"))
    usable, reason = is_usable_page(result)
    assert usable, f"false positive on {result['url']}: {reason}"
    assert reason == ""


def test_every_good_demo_url_has_a_fixture():
    """Guards against silently losing coverage of a demo.yaml source."""
    config = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    demo_urls = {source["url"] for question in config for source in question["sources"]}
    known_bad_urls = {load(name)["url"] for name in KNOWN_BAD}
    covered = {json.loads(path.read_text(encoding="utf-8"))["url"] for path in good_fixtures()}
    assert demo_urls - known_bad_urls == covered


def test_failed_fetch_is_unusable():
    usable, reason = is_usable_page(
        {"url": "https://example.com", "ok": False, "markdown": None, "title": None, "error": "429"}
    )
    assert (usable, reason) == (False, UNUSABLE_FETCH_FAILED)


def test_empty_markdown_is_unusable():
    usable, reason = is_usable_page({"url": "https://example.com", "ok": True, "markdown": "  ", "title": "Planet"})
    assert (usable, reason) == (False, UNUSABLE_EMPTY)


class _FakeScrape:
    """Mimics the steel-sdk scrape result well enough for _shape."""

    def __init__(self, title, markdown):
        self.metadata = type("Metadata", (), {"title": title, "status_code": 200})()
        self.content = type("Content", (), {"markdown": markdown})()
        self.links = []


def test_shape_marks_usable_fields():
    good = load(sorted(good_fixtures())[0].stem)
    shaped = _shape(good["url"], result=_FakeScrape(good["title"], good["markdown"]))
    assert shaped["usable"] is True
    assert shaped["unusable_reason"] == ""

    skeleton = load("bad_space_nav_skeleton")
    shaped = _shape(skeleton["url"], result=_FakeScrape(skeleton["title"], skeleton["markdown"]))
    assert shaped["usable"] is False
    assert shaped["unusable_reason"] == UNUSABLE_NAV_SKELETON

    failed = _shape("https://example.com", error=RuntimeError("boom"))
    assert failed["usable"] is False
    assert failed["unusable_reason"] == UNUSABLE_FETCH_FAILED


def test_usable_page_does_not_mutate_the_result():
    result = load("bad_space_nav_skeleton")
    before = json.dumps(result, sort_keys=True)
    is_usable_page(result)
    assert json.dumps(result, sort_keys=True) == before
