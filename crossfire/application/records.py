"""实体写进结果文件时的形状。"""

from typing import Any

from crossfire.domain import Page, RunResult, is_usable_page


def page_record(page: Page) -> dict[str, Any]:
    """结果文件和缓存文件里的页面，比 Page.to_dict 多两个派生键 usable / unusable_reason。"""
    usable, reason = is_usable_page(page)
    return {**page.to_dict(), "usable": usable, "unusable_reason": "" if reason is None else reason.value}


def run_record(result: RunResult) -> dict[str, Any]:
    """out/runs/*.json 的完整内容。与 RunResult.to_dict 只差在页面多了 usable 两个键。"""
    return {**result.to_dict(), "pages": [page_record(page) for page in result.pages]}
