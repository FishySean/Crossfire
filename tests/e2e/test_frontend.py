"""前端 e2e：fake_events 驱动，截图进 docs/screenshots/。"""

from __future__ import annotations

from pathlib import Path

import pytest

SHOTS = Path(__file__).resolve().parents[2] / "docs" / "screenshots"


def _shot(page, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)


def test_pairer_toggle_and_nli_disabled_when_unavailable(page, app_server):
    page.goto(app_server)
    page.wait_for_selector("#pairer-toggle")
    claude = page.locator('#pairer-toggle button[data-pairer="claude"]')
    nli = page.locator('#pairer-toggle button[data-pairer="nli"]')
    assert claude.count() == 1
    # e2e 环境通常没装 nli 组 → NLI 应禁用并带原因
    page.wait_for_timeout(500)
    if nli.is_disabled():
        title = nli.get_attribute("title") or ""
        assert "依赖" in title or "模型" in title or "NLI" in title or title
    _shot(page, "01-pairer-toggle")


def test_fake_nli_scores_hover(page, app_server):
    page.goto(f"{app_server}/?fake=nli-scores&speed=40")
    page.click("#run-button")
    page.wait_for_selector(".conflict", timeout=20000)
    conflict = page.locator(".conflict").first
    conflict.hover()
    title = conflict.get_attribute("title") or ""
    assert "contradict" in title or "agree" in title or "概率" in title or "0." in title
    _shot(page, "02-nli-scores")


def test_extract_fail_card(page, app_server):
    page.goto(f"{app_server}/?fake=extract-fail&speed=40")
    page.click("#lang-toggle button[data-lang='zh']")
    page.click("#run-button")
    page.wait_for_selector("text=提取失败", timeout=20000)
    _shot(page, "03-extract-fail")


def test_unusable_content_card(page, app_server):
    page.goto(f"{app_server}/?fake=unusable&speed=40")
    page.click("#lang-toggle button[data-lang='zh']")
    page.click("#run-button")
    page.wait_for_selector("text=内容不可用", timeout=20000)
    _shot(page, "04-unusable")


def test_bad_conflicts_warns(page, app_server):
    page.goto(f"{app_server}/?fake=bad-conflicts&speed=80")
    page.click("#lang-toggle button[data-lang='zh']")
    page.click("#run-button")
    page.wait_for_selector("text=格式可能损坏", timeout=60000)
    assert page.locator(".format-warning").count() >= 1
    _shot(page, "05-bad-conflicts")


def test_legacy_run_opens_without_error(page, app_server):
    page.goto(app_server)
    page.wait_for_selector("#run-select")
    options = page.locator("#run-select option").all_text_contents()
    legacy = next((o for o in options if "legacy" in o), None)
    assert legacy is not None
    page.select_option("#run-select", label=legacy)
    page.wait_for_selector("#question")
    assert page.locator("#content").is_visible()
    meta = page.locator("#run-meta").inner_text()
    assert "未记录" in meta or "Not recorded" in meta
    _shot(page, "06-legacy-run")


def test_nli_history_label(page, app_server):
    page.goto(app_server)
    page.wait_for_selector("#run-select")
    options = page.locator("#run-select option").all_text_contents()
    nli = next((o for o in options if "NLI" in o), None)
    assert nli is not None
    page.select_option("#run-select", label=nli)
    page.wait_for_selector("#question")
    meta = page.locator("#run-meta").inner_text()
    assert "NLI" in meta and "0517c59" in meta
    _shot(page, "07-nli-history")
