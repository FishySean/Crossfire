"""实体写进结果文件时的形状。"""

from typing import Any

from crossfire.domain import Page, is_usable_page


def page_record(page: Page) -> dict[str, Any]:
    """结果文件和缓存文件里的页面，比 Page.to_dict 多两个派生键 usable / unusable_reason。"""
    usable, reason = is_usable_page(page)
    return {**page.to_dict(), "usable": usable, "unusable_reason": "" if reason is None else reason.value}
