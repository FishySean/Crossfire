"""核实主张的发布日期是不是页面上真有的，防止模型用 as_of 冒充发布日。"""

import re
from datetime import date


def published_date_appears_on_page(markdown: str | None, day: date) -> bool:
    """页面正文里是否出现这一天（常见写法都算）。"""
    if not markdown:
        return False
    y, m, d = day.year, day.month, day.day
    month_name = day.strftime("%B")  # November
    month_abbr = day.strftime("%b")  # Nov
    patterns = [
        rf"{y}-{m:02d}-{d:02d}",
        rf"{y}/{m:02d}/{d:02d}",
        rf"{m:02d}/{d:02d}/{y}",
        rf"{d}/{m:02d}/{y}",
        rf"{d}\s+{month_name}\s+{y}",
        rf"{month_name}\s+{d},?\s+{y}",
        rf"{d}\s+{month_abbr}\.?\s+{y}",
        rf"{month_abbr}\.?\s+{d},?\s+{y}",
        rf"{y}年{m}月{d}日",
        rf"{y}年{m:02d}月{d:02d}日",
    ]
    return any(re.search(pattern, markdown, flags=re.IGNORECASE) for pattern in patterns)


def scrub_as_of_published_date(
    published_date: str | None,
    as_of: date,
    markdown: str | None,
) -> tuple[str | None, str | None]:
    """若 published_date 等于 as_of 但原文找不到该日，改成 None 并返回警告。

    返回 (纠正后的日期, 警告文案或 None)。
    """
    if published_date is None:
        return None, None
    if published_date != as_of.isoformat():
        return published_date, None
    if published_date_appears_on_page(markdown, as_of):
        return published_date, None
    warning = (
        f"published_date={published_date} 等于 as_of，但页面原文未出现该日期，已改为 null"
    )
    return None, warning
