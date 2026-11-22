"""安全 markdown：先转义 HTML，再只恢复加粗/换行/列表/http(s) 链接。"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "web" / "static" / "safe_markdown.js"


def _render(raw: str) -> str:
    script = f"""
const m = require({str(MODULE)!r});
process.stdout.write(m.safeMarkdownHtml({raw!r}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_script_and_onerror_are_escaped_not_executable():
    html = _render('<script>alert(1)</script><img src=x onerror=alert(1)>')
    assert "<script" not in html.lower()
    assert "<img" not in html.lower()
    assert "&lt;script&gt;" in html.lower()
    assert "&lt;img" in html.lower()
    assert "onerror=alert(1)" in html  # 仅作为转义后的文字残留


def test_javascript_links_are_not_turned_into_anchors():
    html = _render("[click me](javascript:alert(1)) and [ok](https://example.com/a)")
    assert "<a " in html
    assert 'href="https://example.com/a"' in html
    assert "javascript:" in html  # 原文还在，但是转义文本
    assert "href=\"javascript:" not in html.lower()
    assert "href='javascript:" not in html.lower()


def test_bold_and_newlines_still_work_after_escaping():
    html = _render("说 **Python 3.14.7** 才对\n下一行")
    assert "<strong>Python 3.14.7</strong>" in html
    assert "<br>" in html
    assert "**" not in html
