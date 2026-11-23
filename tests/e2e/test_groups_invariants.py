"""分组证据区不变量：卡片不重叠、可见标题可区分、Logo 完整、KPI 到位。"""

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

# README 首图历史栏只留演示级条目，不露出 ten-sources 等压测假数据。
README_HISTORY_KEEP = {
    "nvidia-ceo-ask.json",
    "apple-ceo-current.json",
    "python-latest-stable.json",
}


def _force_lang_en(page) -> None:
    """窄视口侧栏移出屏幕时 #lang-toggle 不可点；直接走与按钮相同的 setLang 路径。"""
    page.evaluate(
        """() => {
          localStorage.setItem('crossfire-lang', 'en');
          const btn = document.querySelector(
            '#lang-toggle-top button[data-lang="en"], #lang-toggle button[data-lang="en"]'
          );
          if (btn) btn.click();
          else document.documentElement.lang = 'en';
        }"""
    )
    page.wait_for_function("() => document.documentElement.lang === 'en'")


def _select_run(page, filename: str) -> None:
    page.wait_for_selector("#run-select option")
    page.select_option("#run-select", value=filename)
    page.wait_for_selector("#content:not(.hidden)")
    page.wait_for_selector("#groups-view .group-card, #groups-view .groups-empty-summary")


def _wait_kpis_settled(page) -> None:
    page.wait_for_function(
        """() => {
          const nodes = [...document.querySelectorAll('#metrics-strip .metric-value')];
          if (nodes.length !== 4) return false;
          return nodes.every((n) => n.textContent === (n.dataset.target || ''));
        }""",
        timeout=5000,
    )


def _assert_group_invariants(page, *, check_logo: bool = True) -> None:
    result = page.evaluate(
        """(checkLogo) => {
          if (checkLogo) {
            const brand = document.querySelector('#brand-name');
            // 侧栏抽屉关闭时仍测量布局宽度；打开时再断言一次由截图用例负责。
            const sidebar = document.querySelector('#sidebar');
            const fixedDrawer = sidebar && getComputedStyle(sidebar).position === 'fixed';
            const sidebarVisible = !fixedDrawer || sidebar.classList.contains('open');
            if (brand && sidebarVisible && brand.scrollWidth > brand.clientWidth + 1) {
              return {ok: false, reason: `logo clipped ${brand.scrollWidth}>${brand.clientWidth}`};
            }
          }
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
            const domain = el.querySelector('.group-card-domain');
            const pageLabel = el.querySelector('.group-card-page');
            for (const node of [domain, pageLabel].filter(Boolean)) {
              if (node.scrollWidth > node.clientWidth + 1) {
                return {ok: false, reason: `text overflow in ${node.className}`};
              }
            }
          }
          // 可见区分标签：同域名多页时 page 行必须出现且可见文本互不相同
          const visibleKeys = cards.map((el) => {
            const page = el.querySelector('.group-card-page');
            const domain = el.querySelector('.group-card-domain');
            const pageText = page && getComputedStyle(page).display !== 'none'
              ? (page.innerText || '').trim() : '';
            const domainText = (domain?.innerText || '').trim();
            return pageText || domainText;
          });
          const dup = visibleKeys.find((t, i) => t && visibleKeys.indexOf(t) !== i);
          if (dup) return {ok: false, reason: `duplicate visible title ${dup}`};
          return {ok: true, visibleKeys};
        }""",
        check_logo,
    )
    assert result["ok"], result.get("reason")


def _prepare_readme_history(page) -> None:
    page.evaluate(
        """(keep) => {
          const select = document.querySelector('#run-select');
          if (!select) return;
          for (const opt of [...select.options]) {
            if (!keep.includes(opt.value)) opt.remove();
          }
        }""",
        list(README_HISTORY_KEEP),
    )


@pytest.mark.parametrize("filename", FIXTURES)
@pytest.mark.parametrize("viewport", VIEWPORTS, ids=lambda v: f"{v['width']}x{v['height']}")
def test_grouped_evidence_invariants(app_server, browser, filename, viewport):
    context = browser.new_context(
        viewport=viewport,
        reduced_motion="reduce",
    )
    pg = context.new_page()
    pg.set_default_timeout(20000)
    try:
        pg.goto(app_server)
        _force_lang_en(pg)
        # 窄屏侧栏默认收起：打开后再验 Logo，避免对离屏节点误判
        if viewport["width"] < 1200:
            pg.click("#sidebar-toggle")
            pg.wait_for_function(
                "() => document.querySelector('#sidebar')?.classList.contains('open')"
            )
        _select_run(pg, filename)
        _wait_kpis_settled(pg)
        assert pg.locator("#groups-view").is_visible()
        _assert_group_invariants(pg)

        # 英文 UI 下，分组/比对界面字不应出现中文（主张原文除外）
        # 先展开一张卡，确保 .group-card-pairs 进 DOM 可见文本
        card = pg.locator("#groups-view .group-card").first
        if card.count():
            card.click()
        ui_bits = pg.evaluate(
            """() => {
              const parts = [];
              for (const sel of [
                '#view-toggle',
                '.group-column-head',
                '.groups-empty-summary',
                '.group-card-pairs',
                '.group-card-tier',
              ]) {
                for (const n of document.querySelectorAll(sel)) {
                  parts.push(n.innerText || '');
                }
              }
              return parts.join('\\n');
            }"""
        )
        assert not any("\u4e00" <= ch <= "\u9fff" for ch in ui_bits), ui_bits

        if filename == "same-domain-three.json":
            pages = pg.locator("#groups-view .group-card-page")
            assert pages.count() >= 2
            texts = pages.all_inner_texts()
            assert any("wikipedia" in t.lower() or "·" in t for t in texts)

        if filename == "nvidia-ceo-ask.json" and viewport["width"] == 1440:
            SHOTS.mkdir(parents=True, exist_ok=True)
            _prepare_readme_history(pg)
            # 收起刚才展开的卡，拍干净首屏
            expanded = pg.locator("#groups-view .group-card.expanded")
            if expanded.count():
                expanded.first.click()
            _wait_kpis_settled(pg)
            pg.screenshot(path=str(SHOTS / "22-groups-nvidia-above-fold.png"), full_page=False)
            wiki = pg.locator("#groups-view .group-card", has_text="wikipedia").first
            if wiki.count() == 0:
                wiki = pg.locator("#groups-view .group-card").first
            wiki.click()
            pg.wait_for_selector("#groups-view .group-card.expanded .group-card-pairs li")
            pg.screenshot(path=str(SHOTS / "23-groups-nvidia-expanded.png"), full_page=False)
            # KPI 等于 summary（动画已结束 / reduced-motion）
            summary = pg.evaluate(
                """async () => {
                  const name = document.querySelector('#run-select').value;
                  const run = await fetch('/api/runs/' + encodeURIComponent(name)).then(r => r.json());
                  return run.summary?.counts || null;
                }"""
            )
            assert summary is not None
            values = [int(v) for v in pg.locator("#metrics-strip .metric-value").all_inner_texts()]
            assert values == [
                summary["sources"],
                summary["pairs"],
                summary["faulty_sources"],
                summary["scope_sources"],
            ]
            # 展开比对行无中文界面字、关系只写一次
            pair_text = pg.locator("#groups-view .group-card.expanded .group-card-pairs").inner_text()
            assert not any("\u4e00" <= ch <= "\u9fff" for ch in pair_text), pair_text
            assert "本地" not in pair_text
            first_line = pair_text.splitlines()[0]
            assert first_line.count("agree") + first_line.count("contradict") <= 1
    finally:
        context.close()


def test_history_shows_question_not_filename(page, app_server):
    page.goto(app_server)
    page.wait_for_selector("#run-select option")
    page.select_option("#run-select", value="nvidia-ceo-ask.json")
    label = page.locator("#run-select option:checked").inner_text()
    assert "nvidia-ceo-ask.json" not in label
    assert "CEO" in label or "NVDIA" in label or "NVIDIA" in label.upper() or "Who" in label
    for opt in page.locator("#run-select option").all_inner_texts():
        assert not opt.endswith(".json")
