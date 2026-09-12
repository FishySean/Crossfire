"""Capture page fixtures used by the offline usability tests.

Good pages are fetched once over plain HTTP and converted to a Steel-like markdown
payload. Bad pages cannot be reproduced without a Steel session (the soft blocks
depend on datacenter IPs), so they are written from the recorded shape of the four
known failures. Run manually; the tests themselves never touch the network.
"""

import gzip
import json
import re
import urllib.request
import zlib
from html.parser import HTMLParser
from pathlib import Path

import yaml

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "pages"
QUESTIONS = Path(__file__).resolve().parents[1] / "questions" / "demo.yaml"
SKIP_TAGS = {"script", "style", "noscript", "svg", "head"}
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"


class MarkdownExtractor(HTMLParser):
    """Minimal HTML -> markdown conversion good enough to mimic Steel's payload."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.links = []
        self._skip = 0
        self._href = None
        self._link_text = []
        self.title = None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "a":
            self._href = dict(attrs).get("href")
            self._link_text = []
        elif tag in {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag == "a":
            label = " ".join("".join(self._link_text).split())
            if label:
                href = self._href or ""
                self.parts.append(f"[{label}]({href})")
                self.links.append({"text": label, "url": href})
            self._href = None
            self._link_text = []

    def handle_data(self, data):
        if self._in_title:
            self.title = " ".join(((self.title or "") + data).split())
            return
        if self._skip:
            return
        if self._href is not None:
            self._link_text.append(data)
            return
        self.parts.append(data)

    def markdown(self):
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n\s*", "\n\n", text)
        return text.strip()


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        encoding = (response.headers.get("Content-Encoding") or "").lower()
        status = response.status
    if encoding == "gzip":
        raw = gzip.decompress(raw)
    elif encoding == "deflate":
        raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    body = raw.decode("utf-8", errors="replace")
    parser = MarkdownExtractor()
    parser.feed(body)
    return {
        "url": url,
        "ok": True,
        "title": parser.title,
        "markdown": parser.markdown(),
        "links": parser.links,
        "error": None,
        "status_code": status,
    }


def nav_only_markdown():
    """Skeleton page: navigation links only, no prose (space.com datacenter block)."""
    sections = [
        ("News", ["Tech", "Science", "Space Exploration", "Astronomy", "Skywatching", "Search for Life"]),
        ("Space Exploration", ["Launches & Spacecraft", "Missions", "Artemis", "SpaceX", "NASA", "ISS"]),
        ("Astronomy", ["Stargazing", "Solar System", "Sun", "Moon", "Planets", "Exoplanets", "Black Holes"]),
        ("Entertainment", ["Space Movies", "Space Books", "Space Games", "Reviews"]),
        ("Shopping", ["Telescopes", "Binoculars", "Cameras", "Star Projectors", "Drones", "Deals"]),
        ("More", ["About Us", "Contact Us", "Newsletter", "Advertise", "Careers", "Terms", "Privacy Policy"]),
    ]
    lines = ["[Space.com](https://www.space.com)", "[Subscribe](https://www.space.com/subscribe)"]
    links = [
        {"text": "Space.com", "url": "https://www.space.com"},
        {"text": "Subscribe", "url": "https://www.space.com/subscribe"},
    ]
    for section, items in sections:
        lines.append(f"\n## {section}")
        for item in items:
            slug = item.lower().replace(" ", "-").replace("&", "and")
            url = f"https://www.space.com/{slug}"
            lines.append(f"[{item}]({url})")
            links.append({"text": item, "url": url})
    headlines = [
        "SpaceX Starship launches on 11th test flight",
        "Northern lights could be visible in these US states tonight",
        "Best telescopes for beginners in 2026: tried and tested",
        "NASA's Artemis 2 astronauts train for lunar flyby",
        "Watch a green comet streak past the Big Dipper this week",
        "Euclid telescope releases first deep field images",
        "How to photograph the Milky Way with a smartphone",
        "Blue Origin New Glenn rocket rolls out to the pad",
        "Amateur astronomer spots new supernova in nearby galaxy",
        "James Webb Space Telescope finds water on distant exoplanet",
        "Total solar eclipse 2026: everything you need to know",
        "ISS crew completes spacewalk to install new solar array",
    ]
    lines.append("\n## Trending")
    for index, headline in enumerate(headlines):
        url = f"https://www.space.com/story-{index}"
        lines.append(f"[{headline}]({url})")
        links.append({"text": headline, "url": url})

    lines.append("\n## Most Popular")
    for index, headline in enumerate(headlines):
        url = f"https://www.space.com/popular-{index}"
        lines.append(f"[{headline}]({url})")
        links.append({"text": headline, "url": url})

    lines.append("\n[Sign in](https://www.space.com/sign-in) [Register](https://www.space.com/register)")
    links += [
        {"text": "Sign in", "url": "https://www.space.com/sign-in"},
        {"text": "Register", "url": "https://www.space.com/register"},
    ]
    lines.append("\n© Future US, Inc. Full 7th Floor, 130 West 42nd Street, New York, NY 10036.")
    return "\n".join(lines), links


def bad_pages():
    nav_markdown, nav_links = nav_only_markdown()
    return {
        "bad_britannica_softblock": {
            "url": "https://www.britannica.com/science/planet",
            "ok": True,
            "title": "planet | Definition, Characteristics, & Facts | Britannica",
            "markdown": "Access Denied\n\nReference #18.6a1ef17.1760000000",
            "links": [],
            "error": None,
            "status_code": 200,
        },
        "bad_thenewstack_page_not_found": {
            "url": "https://thenewstack.io/python-3-13-whats-new/",
            "ok": True,
            "title": "Page not found",
            "markdown": "# Page not found\n\nThe page you were looking for does not exist. "
            "It may have been moved, or removed altogether.\n\n"
            "[Home](https://thenewstack.io) [Latest](https://thenewstack.io/latest)",
            "links": [
                {"text": "Home", "url": "https://thenewstack.io"},
                {"text": "Latest", "url": "https://thenewstack.io/latest"},
            ],
            "error": None,
            "status_code": 200,
        },
        "bad_theregister_404_title": {
            "url": "https://www.theregister.com/2024/10/07/python_313/",
            "ok": True,
            "title": "404 - The Register",
            "markdown": "# Sorry, that page could not be found\n\n"
            "It may have been retired, or you may have mistyped the address.\n\n"
            "[The Register](https://www.theregister.com) [Search](https://www.theregister.com/search/)",
            "links": [
                {"text": "The Register", "url": "https://www.theregister.com"},
                {"text": "Search", "url": "https://www.theregister.com/search/"},
            ],
            "error": None,
            "status_code": 200,
        },
        "bad_space_nav_skeleton": {
            "url": "https://www.space.com/how-many-planets-in-the-solar-system",
            "ok": True,
            "title": "How many planets are in the solar system? | Space",
            "markdown": nav_markdown,
            "links": nav_links,
            "error": None,
            "status_code": 200,
        },
    }


def good_urls():
    config = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    return [source["url"] for question in config for source in question["sources"]]


def main():
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in bad_pages().items():
        (FIXTURE_DIR / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"wrote {name}")

    for url in good_urls():
        slug = "good_" + re.sub(r"[^a-z0-9]+", "_", url.split("://", 1)[1].lower()).strip("_")
        try:
            payload = fetch(url)
        except Exception as e:  # noqa: BLE001 - fixture capture is best effort
            print(f"skipped {url}: {e}")
            continue
        (FIXTURE_DIR / f"{slug}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"wrote {slug} ({len(payload['markdown'])} chars)")


if __name__ == "__main__":
    main()
