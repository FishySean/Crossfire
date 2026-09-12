import json
import os

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1000
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

严格按下面的字段返回一个 JSON 对象：
- claim: 该网页针对上述问题的主张，用一句话概括。如果这个网页没有回答该问题，返回 null
- evidence: 支撑该主张的原文句子，照抄网页原文不要改写，不超过 20 个词。claim 为 null 时返回 null
- source_type: 这个页面的性质，取值如 official_documentation / news_article / encyclopedia / blog / forum / other
- confidence: 0 到 1 之间的数字，表示你对"这确实是该网页的立场"有多确信，不是对主张本身真假的判断
- published_date: 页面的发布日期或最后更新日期，格式 YYYY-MM-DD。页面里找不到就返回 null

published_date 很重要，很多来源之间的矛盾其实是时间差造成的，请尽力在正文里寻找日期线索。

只输出这个 JSON 对象本身。不要 markdown 代码围栏，不要任何前言、解释或补充说明。"""


def extract_claim(question: str, page: dict) -> dict:
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    prompt = EXTRACT_PROMPT.format(
        question=question,
        url=page["url"],
        title=page.get("title") or "(无标题)",
        content=(page.get("markdown") or "")[:MAX_CONTENT_CHARS],
    )
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()

    result = {
        "url": page["url"],
        "tier": page.get("tier"),
        "claim": None,
        "evidence": None,
        "source_type": None,
        "confidence": None,
        "published_date": None,
        "usage": {
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        },
    }
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        result["parse_error"] = str(e)
        result["raw"] = raw
        return result

    for key in ("claim", "evidence", "source_type", "confidence", "published_date"):
        result[key] = parsed.get(key)
    return result
