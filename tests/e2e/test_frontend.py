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
    page.click("#lang-toggle button[data-lang='zh']")
    page.click("#run-button")
    page.wait_for_selector("#conflicts .conflict", timeout=20000)
    conflict = page.locator("#conflicts .conflict").first
    conflict.hover()
    title = conflict.get_attribute("title") or ""
    assert "contradict" in title or "agree" in title or "概率" in title or "0." in title
    assert "未经校准" in (page.locator("#scores-calibration").inner_text())
    assert page.locator(".score-chip").count() >= 1
    meta = page.locator("#run-meta").inner_text()
    # 合成结果也应立刻标出当前选中的比对器，不能停在「未记录」
    assert "未记录" not in meta
    _shot(page, "02-nli-scores")


def test_extract_fail_card(page, app_server):
    page.goto(f"{app_server}/?fake=extract-fail&speed=40")
    page.click("#lang-toggle button[data-lang='zh']")
    page.click("#run-button")
    page.wait_for_selector("text=提取失败", state="attached", timeout=20000)
    page.click('#view-toggle button[data-view="table"]')
    assert page.locator("#sources >> text=提取失败").count() >= 1
    _shot(page, "03-extract-fail")


def test_unusable_content_card(page, app_server):
    page.goto(f"{app_server}/?fake=unusable&speed=40")
    page.click("#lang-toggle button[data-lang='zh']")
    page.click("#run-button")
    page.wait_for_selector("text=内容不可用", state="attached", timeout=20000)
    page.click('#view-toggle button[data-view="table"]')
    assert page.locator("#sources >> text=内容不可用").count() >= 1
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
    page.select_option("#run-select", value="legacy_no_provenance.json")
    page.wait_for_selector("#question")
    assert page.locator("#content").is_visible()
    meta = page.locator("#run-meta").inner_text()
    assert "未记录" in meta or "Not recorded" in meta
    _shot(page, "06-legacy-run")


def test_ask_confirm_dialog_and_source_progress(page, app_server):
    page.goto(f"{app_server}/?fake=ask-normal&speed=40")
    page.click("#lang-toggle button[data-lang='zh']")
    page.click("#ask-open")
    page.wait_for_selector("#ask-dialog:not(.hidden)")
    page.fill("#ask-input", "当前稳定版 Python 是哪个？")
    page.click("#ask-button")
    page.wait_for_selector("#ask-confirm:not(.hidden)")
    assert "预计" in page.locator("#ask-dialog-estimate").inner_text()
    page.click("#ask-confirm")
    page.wait_for_selector("#source-find-panel:not(.hidden)", timeout=20000)
    assert page.locator("#source-find-list li").count() >= 2
    page.wait_for_selector("#judgment .answer, #judgment .thinking", timeout=60000)
    _shot(page, "09-ask-sources")


def test_ask_insufficient_stops(page, app_server):
    page.goto(f"{app_server}/?fake=ask-insufficient&speed=40")
    page.click("#lang-toggle button[data-lang='zh']")
    page.click("#ask-open")
    page.wait_for_selector("#ask-dialog:not(.hidden)")
    page.click("#ask-button")
    page.wait_for_selector("#ask-confirm:not(.hidden)")
    page.click("#ask-confirm")
    page.wait_for_selector("#error-banner:not(.hidden)", timeout=20000)
    text = page.locator("#error-banner").inner_text()
    assert "来源" in text or "停止" in text
    _shot(page, "10-ask-insufficient")


def test_ask_cost_limit_stops(page, app_server):
    page.goto(f"{app_server}/?fake=ask-cost-limit&speed=40")
    page.click("#lang-toggle button[data-lang='zh']")
    page.click("#ask-open")
    page.wait_for_selector("#ask-dialog:not(.hidden)")
    page.click("#ask-button")
    page.wait_for_selector("#ask-confirm:not(.hidden)")
    page.click("#ask-confirm")
    page.wait_for_selector("#error-banner:not(.hidden)", timeout=20000)
    text = page.locator("#error-banner").inner_text()
    assert "费用" in text or "超限" in text or "停止" in text
    _shot(page, "11-ask-cost-limit")


def test_nli_history_label(page, app_server):
    page.goto(app_server)
    page.wait_for_selector("#run-select")
    page.select_option("#run-select", value="nli_sample.json")
    page.wait_for_selector("#question")
    meta = page.locator("#run-meta").inner_text()
    assert "NLI" in meta and "2f8d20c" in meta
    assert page.locator(".answer strong").count() >= 1
    assert "**" not in page.locator("#judgment .answer").inner_text()
    assert page.locator("#metrics-strip .metric").count() == 4
    foot = page.locator(".card-foot").all_inner_texts()
    assert any("内容所述时间" in text or "Content as of" in text for text in foot)
    # XSS：尖括号必须转义；javascript: 不得变成可点链接；https 可以
    answer_html = page.locator("#judgment .answer").inner_html()
    assert "<script" not in answer_html.lower()
    assert "<img" not in answer_html.lower()
    assert "&lt;script" in answer_html.lower()
    assert "&lt;img" in answer_html.lower()
    assert page.locator("#judgment .answer a[href^='javascript:']").count() == 0
    assert page.locator("#judgment .answer a[href='https://example.com/safe']").count() == 1
    assert page.evaluate("window.__xss") is None
    # provenance：真实格式结果文件要显示 NLI 与 revision 前 7 位
    assert "NLI" in meta and "2f8d20c" in meta
    assert page.locator("#groups-view .group-card").count() >= 1
    assert page.locator("#verdict-headline").inner_text().strip()
    _shot(page, "07-nli-history")


def test_dashboard_groups_table_and_reduced_motion(page, app_server):
    page.emulate_media(reduced_motion="reduce")
    page.goto(app_server)
    page.wait_for_selector("#run-select")
    page.select_option("#run-select", value="nli_sample.json")
    page.wait_for_selector("#content:not(.hidden)")
    assert page.locator("#groups-view").is_visible()
    page.locator('#view-toggle button[data-view="table"]').click()
    page.wait_for_selector("#table-view:not(.hidden)")
    assert page.locator("#sources .card").count() >= 1
    page.locator('#view-toggle button[data-view="groups"]').click()
    page.wait_for_selector("#groups-view:not(.hidden)")
    page.locator("#groups-view .group-card").first.click()
    assert page.locator("#groups-view .group-card.expanded").count() >= 1
    assert page.evaluate(
        "() => matchMedia('(prefers-reduced-motion: reduce)').matches"
    )
    _shot(page, "16-dashboard-groups-table")


def test_dashboard_mobile_shell(page, app_server, browser):
    context = browser.new_context(viewport={"width": 390, "height": 844})
    mobile = context.new_page()
    mobile.set_default_timeout(15000)
    mobile.goto(app_server)
    mobile.wait_for_selector("#sidebar-toggle")
    assert mobile.locator("#sidebar-toggle").is_visible()
    mobile.click("#sidebar-toggle")
    assert "open" in (mobile.locator("#sidebar").get_attribute("class") or "")
    mobile.select_option("#run-select", value="nli_sample.json")
    mobile.wait_for_selector("#question")
    _shot(mobile, "17-dashboard-mobile")
    context.close()
