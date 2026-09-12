from crossfire.llm import call_structured

# 正文截断上限，保留开头。这个值基本等于关掉裁剪，只用来兜住极端长页面烧穿 token。
# 千万不要设到 12000 到 18000 之间：实测在这个区间里，模型会读到半张版本表格，
# 然后自信地报出一个过时的答案。这种错误会流进 pair 和 judge，比主张缺失严重得多。
# 要调低就一路调到 8000 以下，让模型明确说「正文被截断，说不出来」。
MAX_CONTENT_CHARS = 40000

EXTRACT_PROMPT = """你在为一个事实查证引擎工作。下面给你一个网页的正文，以及一个需要查证的问题。
你的任务是判断这个网页针对该问题给出了什么主张。

问题：{question}

网页 URL：{url}
网页标题：{title}
网页正文（可能已被截断）：
---
{content}
---

published_date 很重要，很多来源之间的矛盾其实是时间差造成的，请尽力在正文里寻找日期线索。
confidence 衡量的是「这确实是该网页的立场」，不是对主张本身真假的判断。

请通过 record 工具返回结果。"""

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "claim": {
            "type": ["string", "null"],
            "description": "该网页针对问题的主张，一句话概括。网页没有回答该问题时为 null",
        },
        "evidence": {
            "type": ["string", "null"],
            "description": "支撑该主张的原文句子，照抄网页原文不要改写，不超过 20 个词。claim 为 null 时为 null",
        },
        "source_type": {
            "type": "string",
            "enum": [
                "official_documentation",
                "news_article",
                "encyclopedia",
                "blog",
                "forum",
                "other",
            ],
            "description": "这个页面的性质",
        },
        "confidence": {
            "type": "number",
            "description": "0 到 1，对「这确实是该网页的立场」的确信程度",
        },
        "published_date": {
            "type": ["string", "null"],
            "description": "页面发布或最后更新日期，格式 YYYY-MM-DD。找不到为 null",
        },
    },
    "required": ["claim", "evidence", "source_type", "confidence", "published_date"],
}


def extract_claim(question: str, page: dict) -> dict:
    prompt = EXTRACT_PROMPT.format(
        question=question,
        url=page["url"],
        title=page.get("title") or "(无标题)",
        content=(page.get("markdown") or "")[:MAX_CONTENT_CHARS],
    )
    data = call_structured(prompt, EXTRACT_SCHEMA, "extract")

    result = {
        "url": page["url"],
        "tier": page.get("tier"),
        "claim": data.get("claim"),
        "evidence": data.get("evidence"),
        "source_type": data.get("source_type"),
        "confidence": data.get("confidence"),
        "published_date": data.get("published_date"),
        "usage": data["_usage"],
    }
    if "_failure" in data:
        result["failure"] = data["_failure"]
    return result
