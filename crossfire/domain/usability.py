"""判断抓回来的页面是不是废页。

这是产品对「什么算一个可用来源」的定义，与用哪家抓取服务无关。
"""

import re
import unicodedata
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # 只为类型标注；运行时 models 反过来 import 这里（Page.usable），不能形成循环。
    from crossfire.domain.models import Page

# 可用性阈值：都是模块级常量，方便按实际抓取情况调。
MIN_CONTENT_CHARS = 500  # 正文总宽度下限（软屏蔽页通常只有几十字符）
MIN_PROSE_CHARS = 600  # 去掉链接文字后，成句正文的宽度下限
MIN_PROSE_LINE_CHARS = 60  # 一行要多宽才算“正文”而不是导航条目
MAX_LINK_TEXT_RATIO = 0.85  # 链接文字占可见文字的比例上限（骨架页 >0.9，导航多的正常页约 0.6-0.75）
# 长度门槛都按显示宽度算：汉字、假名、全角标点算 2，其余算 1。30 个汉字的句子和 60 个英文字符一样宽。

# 错误标题：标题按分隔符切段，某一段整段是下面这些之一才算，不做子串匹配。
# 这样 "404 - The Register"、"Attention Required! | Cloudflare" 仍会命中，
# "Highway 404 closure"、"403(b) retirement plan limits" 不会。
ERROR_TITLE_CODES = ("403", "404")
ERROR_TITLE_PHRASES = (
    "page not found",
    "not found",
    "forbidden",
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
_TITLE_SEPARATOR = re.compile(r"\s+[-–—|·]\s+|\s*[|·]\s*|:\s+")
_CODE = "(?:(?:http|error) )?(?:" + "|".join(ERROR_TITLE_CODES) + ")(?: error)?"
_PHRASE = "(?:oops )?(?:" + "|".join(ERROR_TITLE_PHRASES) + ")"
_ERROR_SEGMENT = re.compile(rf"{_CODE}|{_PHRASE}|{_CODE} (?:page )?{_PHRASE}|{_PHRASE} {_CODE}")


def is_error_title(title: str) -> bool:
    for segment in _TITLE_SEPARATOR.split(title):
        normalized = " ".join(re.sub(r"[^\w]+", " ", segment.lower()).split())
        if normalized and _ERROR_SEGMENT.fullmatch(normalized):
            return True
    return False


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def _strip_links(text: str) -> tuple[str, int]:
    """返回 (去掉链接后的文字, 链接文字字符数)。"""
    link_chars = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal link_chars
        link_chars += len(match.group(1).strip())
        return " "

    return _MARKDOWN_LINK.sub(replace, text), link_chars


def _prose_width(text_without_links: str) -> int:
    """统计看起来像正文的宽度：足够宽、且不是纯列表/导航条目的行。"""
    total = 0
    for line in text_without_links.splitlines():
        width = display_width(line.strip().lstrip("#*->|• ").strip())
        if width >= MIN_PROSE_LINE_CHARS:
            total += width
    return total


def is_usable_page(page: "Page") -> tuple[bool, UnusableReason | None]:
    """判断一次抓取结果是否可用。

    覆盖“HTTP 200 但内容废掉”的几类情况：反爬软屏蔽（内容极短）、
    软 404（标题某一段就是 not found / 404）、以及数据中心 IP 只拿到导航骨架页
    （字符数不少，但全是链接、没有成句正文）。status_code 不参与判断。

    返回 (是否可用, 不可用原因)。可用时原因为 None。
    """
    if not page.ok:
        return False, UnusableReason.FETCH_FAILED

    markdown = (page.markdown or "").strip()
    if not markdown:
        return False, UnusableReason.EMPTY

    if is_error_title(page.title or ""):
        return False, UnusableReason.ERROR_TITLE

    if display_width(markdown) < MIN_CONTENT_CHARS:
        return False, UnusableReason.TOO_SHORT

    without_links, link_chars = _strip_links(markdown)
    text_chars = re.sub(r"\s+", "", without_links)
    visible_chars = link_chars + len(text_chars)
    link_ratio = link_chars / visible_chars if visible_chars else 1.0
    if link_ratio > MAX_LINK_TEXT_RATIO:
        return False, UnusableReason.NAV_SKELETON
    # 链接以外的文字全加起来都不够正文下限：缺的是篇幅，不是被导航挤掉了正文。
    if display_width(text_chars) < MIN_PROSE_CHARS:
        return False, UnusableReason.TOO_SHORT
    if _prose_width(without_links) < MIN_PROSE_CHARS:
        return False, UnusableReason.NAV_SKELETON

    return True, None
