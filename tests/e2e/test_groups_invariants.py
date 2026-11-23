"""分组证据区不变量：卡片不重叠、文字不溢出、标题可区分、结论可展开。"""

from __future__ import annotations

import pytest

from tests.e2e.test_frontend import SHOTS

FIXTURES = [
    "nvidia-ceo-ask.json",
    "nodejs-dashboard.json",
    "three-sources.json",
    "ten-sources.json",
    "chinese-long.json",
    "same-domain-three.json",
    "with-failed-source.json",
    "legacy-no-summary-fields.json",
]

VIEWPORTS = [
    {"width": 1440, "height": 900},
    {"width": 1280, "height": 800},
    {"width": 1024, "height": 768},
    {"width": 390, "height": 844},
]


def _select_run(page, filename: str) -> None:
    page.wait_for_selector("#run-select option")
    page.select_option("#run-select", value=filename)
    page.wait_for_selector("#content:not(.hidden)")
    page.wait_for_selector("#groups-view .group-column")


def _assert_group_invariants(page) -> None:
    result = page.evaluate(
        """() => {
          const cards = [...document.querySelectorAll('#groups-view .group-card')];
          const boxes = cards.map((el) => {
            const r = el.getBoundingClientRect();
            return {x: r.x, y: r.y, right: r.right, bottom: r.bottom};
          });
          for (let i = 0; i < boxes.length; i++) {
            for (let j = i + 1; j < boxes.length; j++) {
              const a = boxes[i], b = boxes[j];
              const overlap = !(a.right <= b.x || b.right <= a.x || a.bottom <= b.y || b.bottom <= a.y);
              if (overlap) return {ok: false, reason: `overlap ${i},${j}`};
            }
          }
          for (const el of cards) {
            const title = el.querySelector('.group-card-title');
            const key = el.querySelector('.group-card-key');
            for (const node of [el, title, key].filter(Boolean)) {
              if (node.scrollWidth > node.clientWidth + 1) {
                return {ok: false, reason: `text overflow in ${node.className}`};
              }
            }
          }
          const titles = cards.map((el) => (el.querySelector('.group-card-title')?.textContent || '').trim());
          const dup = titles.find((t, i) => t && titles.indexOf(t) !== i);
          if (dup) return {ok: false, reason: `duplicate title ${dup}`};
          const answer = document.querySelector('#verdict-answer .verdict-answer-text');
          if (answer) {
            const clamped = answer.classList.contains('clamped');
            const expand = document.querySelector('#verdict-answer .answer-expand');
            if (clamped && !expand) return {ok: false, reason: 'answer clamped without expand'};
          }
          return {ok: true, titles};
        }"""
    )
    assert result["ok"], result.get("reason")


@pytest.mark.parametrize("filename", FIXTURES)
@pytest.mark.parametrize("viewport", VIEWPORTS, ids=lambda v: f"{v['width']}x{v['height']}")
def test_grouped_evidence_invariants(app_server, browser, filename, viewport):
    context = browser.new_context(viewport=viewport)
    pg = context.new_page()
    pg.set_default_timeout(20000)
    try:
        pg.goto(app_server)
        _select_run(pg, filename)
        assert pg.locator("#groups-view").is_visible()
        # 等结论展开按钮异步测量完成
        pg.wait_for_timeout(200)
        _assert_group_invariants(pg)
        expand = pg.locator("#verdict-answer .answer-expand")
        if expand.count():
            assert pg.locator("#verdict-answer .verdict-answer-text").evaluate(
                "el => el.classList.contains('clamped')"
            )
            expand.click()
            assert not pg.locator("#verdict-answer .verdict-answer-text").evaluate(
                "el => el.classList.contains('clamped')"
            )
        if filename == "nvidia-ceo-ask.json" and viewport["width"] == 1440:
            SHOTS.mkdir(parents=True, exist_ok=True)
            pg.screenshot(path=str(SHOTS / "22-groups-nvidia-above-fold.png"), full_page=False)
            pg.locator("#groups-view .group-card").first.click()
            pg.screenshot(path=str(SHOTS / "23-groups-nvidia-expanded.png"), full_page=False)
    finally:
        context.close()
