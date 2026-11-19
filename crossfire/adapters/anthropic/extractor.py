from dataclasses import replace
from datetime import date
from typing import Any

from crossfire.adapters.anthropic.client import ClaudeClient, describe_date, prompt_version
from crossfire.domain import Claim, Page, Provenance, Question, SourceType

# 正文截断上限，保留开头。这个值基本等于关掉裁剪，只用来兜住极端长页面烧穿 token。
# 千万不要设到 12000 到 18000 之间：实测在这个区间里，模型会读到半张版本表格，
# 然后自信地报出一个过时的答案。这种错误会流进 pair 和 judge，比主张缺失严重得多。
# 要调低就一路调到 8000 以下，让模型明确说「正文被截断，说不出来」。
MAX_CONTENT_CHARS = 40000

EXTRACT_PROMPT = """你在为一个事实查证引擎工作。下面给你一个网页的正文，以及一个需要查证的问题。
你的任务是判断这个网页针对该问题给出了什么主张。

今天的日期：{as_of}
网页的内容可能比你的训练数据新。页面里出现你不知道的版本、事件、日期，照样如实记录，
不要用你自己的知识去纠正、补全或筛选页面的内容。

问题：{question}

网页 URL：{url}
网页标题：{title}
网页正文（可能已被截断）：
---
{content}
---

提取规则：
1. 页面自己给了术语或状态的定义时，按页面的定义判断，不要按你自己的理解。
2. claim 必须和你引用的 evidence 一致。页面列出多个候选（比如一张表里的好几行）时，按页面的定义挑出
   符合问题条件的那一个；不要挑你最熟悉的那个，也不要挑和你的印象吻合的那个。
3. 保留来源自身的时间口径。页面描述的是它发布时的情况（比如一篇介绍某个新版本的文章），
   claim 要写成「截至 YYYY-MM-DD（该文发布时），……」，不要改写成「目前……」。
   只有页面本身是持续更新的状态页（比如状态表、下载页、实时统计），才可以说「目前」。

published_date 很重要，很多来源之间的矛盾其实是时间差造成的，请尽力在正文里寻找日期线索。
confidence 衡量的是「这确实是该网页的立场」，不是对主张本身真假的判断。

请通过 record 工具返回结果。"""

EXTRACT_SCHEMA: dict[str, Any] = {
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
            "enum": [kind.value for kind in SourceType],
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

_NO_USAGE = {"input_tokens": 0, "output_tokens": 0, "requests": 0}


class ClaudeClaimExtractor:
    def __init__(self, client: ClaudeClient) -> None:
        self._client = client

    @property
    def provenance(self) -> Provenance:
        return Provenance(model=self._client.model, prompt_version=prompt_version(EXTRACT_PROMPT, EXTRACT_SCHEMA))

    def extract(self, question: Question, page: Page, as_of: date | None) -> Claim:
        source = question.source_of(page.url)
        prompt = EXTRACT_PROMPT.format(
            as_of=describe_date(as_of),
            question=question.text,
            url=page.url,
            title=page.title or "(无标题)",
            content=(page.markdown or "")[:MAX_CONTENT_CHARS],
        )

        def parse(data: dict[str, Any]) -> Claim:
            return Claim.from_dict({**data, "url": page.url, "tier": source.tier.value, "usage": _NO_USAGE})

        call = self._client.call(prompt, EXTRACT_SCHEMA, "extract", parse)
        if call.value is not None:
            return replace(call.value, usage=call.usage)
        return Claim(
            source_url=page.url,
            tier=source.tier,
            text=None,
            evidence=None,
            source_type=None,
            published_date=None,
            confidence=None,
            usage=call.usage,
            failure=call.failure,
        )
