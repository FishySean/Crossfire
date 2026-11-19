"""判断抓回来的页面是不是废页。

这是产品对「什么算一个可用来源」的定义，与用哪家抓取服务无关。
"""

import re
from enum import StrEnum

from crossfire.domain.models import Page

# 可用性阈值：都是模块级常量，方便按实际抓取情况调。
MIN_CONTENT_CHARS = 500  # 正文总长度下限（软屏蔽页通常只有几十字符）
MIN_PROSE_CHARS = 600  # 去掉链接文字后，成句正文的长度下限
MIN_PROSE_LINE_CHARS = 60  # 一行要多长才算“正文”而不是导航条目
MAX_LINK_TEXT_RATIO = 0.85  # 链接文字占可见文字的比例上限（骨架页 >0.9，导航多的正常页约 0.6-0.75）
ERROR_TITLE_PATTERNS = (
    "page not found",
    "not found",
    "404",
    "403",
    "access denied",
    "attention required",
    "just a moment",
    "are you a robot",
)


class UnusableReason(StrEnum):
    """值会写进结果文件的 unusable_reason 字段，不能改。"""

    FETCH_FAILED = "fetch_failed"
    EMPTY = "empty_content"
    TOO_SHORT = "too_short"
    ERROR_TITLE = "error_page_title"
    NAV_SKELETON = "nav_skeleton"


_MARKDOWN_LINK = re.compile(r"\[([^\]\n]*)\]\(([^)\s]*)[^)]*\)")


def _strip_links(text: str) -> tuple[str, int]:
    """返回 (去掉链接后的文字, 链接文字字符数)。"""
    link_chars = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal link_chars
        link_chars += len(match.group(1).strip())
        return " "

    return _MARKDOWN_LINK.sub(replace, text), link_chars


def _prose_chars(text_without_links: str) -> int:
    """统计看起来像正文的字符数：足够长、且不是纯列表/导航条目的行。"""
    total = 0
    for line in text_without_links.splitlines():
        stripped = line.strip().lstrip("#*->|• ").strip()
        if len(stripped) >= MIN_PROSE_LINE_CHARS:
            total += len(stripped)
    return total


def is_usable_page(page: Page) -> tuple[bool, UnusableReason | None]:
    """判断一次抓取结果是否可用。

    覆盖“HTTP 200 但内容废掉”的几类情况：反爬软屏蔽（内容极短）、
    软 404（标题写着 not found / 404）、以及数据中心 IP 只拿到导航骨架页
    （字符数不少，但全是链接、没有成句正文）。status_code 不参与判断。

    返回 (是否可用, 不可用原因)。可用时原因为 None。
    """
    if not page.ok:
        return False, UnusableReason.FETCH_FAILED

    markdown = (page.markdown or "").strip()
    if not markdown:
        return False, UnusableReason.EMPTY

    title = (page.title or "").strip().lower()
    if any(pattern in title for pattern in ERROR_TITLE_PATTERNS):
        return False, UnusableReason.ERROR_TITLE

    if len(markdown) < MIN_CONTENT_CHARS:
        return False, UnusableReason.TOO_SHORT

    without_links, link_chars = _strip_links(markdown)
    visible_chars = link_chars + len(re.sub(r"\s+", "", without_links))
    link_ratio = link_chars / visible_chars if visible_chars else 1.0
    if link_ratio > MAX_LINK_TEXT_RATIO or _prose_chars(without_links) < MIN_PROSE_CHARS:
        return False, UnusableReason.NAV_SKELETON

    return True, None
