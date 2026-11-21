import sys
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date
from typing import Any

from crossfire.adapters.anthropic.client import ClaudeCallError, ClaudeClient, prompt_version
from crossfire.application.ports import OnClaim
from crossfire.domain import Claim, Failure, Page, Provenance, Question, SourceType, Usage
from crossfire.domain.published_dates import scrub_as_of_published_date

# 同时在读的页面数。每页的 prompt 有上万 token，并发太高容易撞上账户的每分钟 token 限额（429 不重试）。
DEFAULT_EXTRACT_CONCURRENCY = 4

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
硬性规则：published_date 只能来自页面原文里写明的发布日、更新日或「最后编辑于」。
页面上找不到就填 null。绝对不能用上面的「今天的日期」或 as_of 代替。
维基百科词条通常没有单一发布日，除非原文明确写了 last edited 日期，否则填 null。

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
            "description": (
                "页面原文中的发布或最后更新日期，格式 YYYY-MM-DD。"
                "找不到为 null；禁止用今天的日期或 as_of 代替"
            ),
        },
    },
    "required": ["claim", "evidence", "source_type", "confidence", "published_date"],
}

_NO_USAGE = {"input_tokens": 0, "output_tokens": 0, "requests": 0}


class ClaudeClaimExtractor:
    """Claude 一次只能读一页，所以整批在内部用线程池并发发请求，并发数受 concurrency 限制。"""

    def __init__(self, client: ClaudeClient, concurrency: int = DEFAULT_EXTRACT_CONCURRENCY) -> None:
        self._client = client
        self._concurrency = concurrency

    @property
    def provenance(self) -> Provenance:
        return Provenance(model=self._client.model, prompt_version=prompt_version(EXTRACT_PROMPT, EXTRACT_SCHEMA))

    def extract_all(
        self,
        question: Question,
        pages: Sequence[Page],
        as_of: date,
        on_claim: OnClaim | None = None,
    ) -> list[Claim]:
        results: list[Claim | None] = [None] * len(pages)
        executor = ThreadPoolExecutor(max_workers=self._concurrency)
        try:
            futures: dict[Future[Claim], int] = {
                executor.submit(self._extract_or_fail, question, page, as_of): index for index, page in enumerate(pages)
            }
            # 回调在调用方线程里按完成顺序触发，事件推送方不用处理多线程。
            for future in as_completed(futures):
                index = futures[future]
                claim = future.result()
                results[index] = claim
                if on_claim:
                    on_claim(index, claim)
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
        return [claim for claim in results if claim is not None]

    def _extract_or_fail(self, question: Question, page: Page, as_of: date) -> Claim:
        # 端口约定 extract_all 不抛异常。网络重试用尽、鉴权失败、额度不足都落到这里。
        try:
            return self.extract(question, page, as_of)
        except ClaudeCallError as e:
            return self._failed(question, page, str(e), e.usage)
        except Exception as e:
            # 不是 API 抛的，不知道请求有没有发出去，请求数记成未知，不编一个数。
            return self._failed(question, page, f"{type(e).__name__}: {e}", Usage(0, 0, None))

    def _failed(self, question: Question, page: Page, detail: str, usage: Usage) -> Claim:
        print(f"❌ [llm] extract 调用抛出异常，这一页记为失败：{detail}", file=sys.stderr)
        return Claim(
            source_url=page.url,
            tier=question.source_of(page.url).tier,
            text=None,
            evidence=None,
            source_type=None,
            published_date=None,
            confidence=None,
            usage=usage,
            failure=Failure(step="extract", detail=detail, raw=None),
        )

    def extract(self, question: Question, page: Page, as_of: date) -> Claim:
        """单页提取。结构化失败返回带 failure 的 Claim；API 异常照常抛 ClaudeCallError，由 extract_all 接住。"""
        source = question.source_of(page.url)
        prompt = EXTRACT_PROMPT.format(
            as_of=as_of.isoformat(),
            question=question.text,
            url=page.url,
            title=page.title or "(无标题)",
            content=(page.markdown or "")[:MAX_CONTENT_CHARS],
        )

        def parse(data: dict[str, Any]) -> Claim:
            return Claim.from_dict({**data, "url": page.url, "tier": source.tier.value, "usage": _NO_USAGE})

        call = self._client.call(prompt, EXTRACT_SCHEMA, "extract", parse)
        if call.value is not None:
            claim = replace(call.value, usage=call.usage)
            cleaned, warning = scrub_as_of_published_date(claim.published_date, as_of, page.markdown)
            if warning:
                print(f"⚠️  [llm] extract {page.url}：{warning}", file=sys.stderr)
                claim = replace(claim, published_date=cleaned)
            return claim
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
