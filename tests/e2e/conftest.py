"""Playwright e2e：用 fake_events 驱动，不起真实 Claude / Steel。"""

from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "docs" / "screenshots"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def app_server(tmp_path_factory):
    base = tmp_path_factory.mktemp("crossfire-e2e")
    runs = base / "runs"
    runs.mkdir()
    # 旧结果：无 provenance → 未记录
    (runs / "legacy_no_provenance.json").write_text(
        json.dumps(
            {
                "question_id": "legacy",
                "question": "旧结果没有比对器记录",
                "mode": "cached",
                "started_at": "2026-09-01T00:00:00+00:00",
                "as_of": None,
                "elapsed_seconds": 1.0,
                "sources": [{"url": "https://a.example/", "tier": "primary"}],
                "pages_fetched": 1,
                "pages_failed": 0,
                "claude_calls": 0,
                "failures": [],
                "steps": {},
                "provenance": None,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "pages": [],
                "claims": [],
                "pairs": [],
                "judgment": {
                    "answer": "legacy",
                    "confidence": 0.5,
                    "reasoning": "x",
                    "conflicts": [],
                    "trusted_sources": [],
                    "usage": {"input_tokens": 0, "output_tokens": 0, "requests": 0},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    # NLI 历史结果样例（带 scores）
    (runs / "nli_sample.json").write_text(
        json.dumps(
            {
                "question_id": "nli-sample",
                "question": "NLI 样例",
                "mode": "cached",
                "started_at": "2026-11-22T00:00:00+00:00",
                "as_of": "2026-09-12",
                "elapsed_seconds": 2.0,
                "sources": [
                    {"url": "https://a.example/", "tier": "primary"},
                    {"url": "https://b.example/", "tier": "news"},
                ],
                "pages_fetched": 2,
                "pages_failed": 0,
                "claude_calls": 3,
                "failures": [],
                "steps": {},
                "provenance": {
                    "extract": {"model": "claude-sonnet-4-6", "prompt_version": "x"},
                    "pair": {
                        "model": "FishySean/crossfire-pairer",
                        "prompt_version": None,
                        "implementation": "nli",
                        "revision": "0517c59dfa13038226b4b66c3fa6b605b9215df5",
                    },
                    "judge": {"model": "claude-sonnet-4-6", "prompt_version": "y"},
                },
                "total_input_tokens": 10,
                "total_output_tokens": 5,
                "pages": [
                    {"url": "https://a.example/", "ok": True, "usable": True, "unusable_reason": ""},
                    {"url": "https://b.example/", "ok": True, "usable": True, "unusable_reason": ""},
                ],
                "claims": [
                    {
                        "url": "https://a.example/",
                        "tier": "primary",
                        "claim": "版本是 3.14.7",
                        "evidence": "e",
                        "source_type": "official_documentation",
                        "published_date": None,
                        "content_date": "2026-09-12",
                        "content_date_evidence": "Python 3.14.7 released",
                        "confidence": 0.9,
                        "usage": {"input_tokens": 1, "output_tokens": 1, "requests": 1},
                    },
                    {
                        "url": "https://b.example/",
                        "tier": "news",
                        "claim": "版本是 3.13",
                        "evidence": "e",
                        "source_type": "blog",
                        "published_date": None,
                        "content_date": "2024-10-07",
                        "content_date_evidence": "Python 3.13 was published on October 7, 2024",
                        "confidence": 0.8,
                        "usage": {"input_tokens": 1, "output_tokens": 1, "requests": 1},
                    },
                ],
                "pairs": [
                    {
                        "a": "https://a.example/",
                        "b": "https://b.example/",
                        "relation": "contradict",
                        "nature": "本地 NLI",
                        "usage": {"input_tokens": 0, "output_tokens": 0, "requests": 0},
                        "scores": {
                            "agree": 0.02,
                            "contradict": 0.9,
                            "same_question_different_scope": 0.05,
                            "unrelated": 0.03,
                        },
                    }
                ],
                "judgment": {
                    "answer": (
                        "最新稳定版是 **Python 3.14.7**。"
                        "<script>window.__xss=1</script>"
                        "<img src=x onerror=window.__xss=1>"
                        "[坏链](javascript:window.__xss=1)"
                        "[好链](https://example.com/safe)"
                    ),
                    "confidence": 0.9,
                    "reasoning": "采信一手来源。",
                    "conflicts": ["3.14.7 vs 3.13"],
                    "trusted_sources": ["https://a.example/"],
                    "usage": {"input_tokens": 1, "output_tokens": 1, "requests": 1},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    questions = base / "questions.yaml"
    questions.write_text(
        yaml.safe_dump(
            [
                {
                    "id": "python-latest-version",
                    "question": "Python 目前的最新稳定版本是哪一个？",
                    "sources": [{"url": "https://www.python.org/downloads/", "tier": "primary"}],
                }
            ],
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    port = _free_port()
    env = {
        **dict(**{k: v for k, v in __import__("os").environ.items()}),
        "CROSSFIRE_RUNS_DIR": str(runs),
        "CROSSFIRE_QUESTIONS_FILE": str(questions),
        "ANTHROPIC_API_KEY": "",
        "STEEL_API_KEY": "",
        "PAIRER": "claude",
    }
    # 清掉可能污染的 key
    env.pop("ANTHROPIC_API_KEY", None)
    env["ANTHROPIC_API_KEY"] = ""
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "web.server:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("e2e server failed to start")
    SHOTS.mkdir(parents=True, exist_ok=True)
    yield url
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
def page(app_server, browser):
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    pg = context.new_page()
    pg.set_default_timeout(15000)
    yield pg
    context.close()
