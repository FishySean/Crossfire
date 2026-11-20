"""用 Claude 的 web_search 服务端工具找来源。

只返回搜索结果里真实出现过的 URL。模型凭记忆编的网址会被硬过滤掉。
"""

import sys
from collections.abc import Sequence
from datetime import date
from typing import Any
from urllib.parse import urldefrag

from crossfire.adapters.anthropic.client import ClaudeCallError, ClaudeClient
from crossfire.domain import CandidateSource, Tier, Usage

# web_search 单价：$10 / 1000 次搜索（另加 token）。查自
# https://docs.anthropic.com/en/docs/about-claude/pricing ，2026-11-20。
WEB_SEARCH_PER_THOUSAND_USD = 10.0
DEFAULT_MAX_SEARCHES = 6
RECORD_TOOL = "record_sources"

FIND_PROMPT = """你在为一个事实查证引擎找来源。问题是：

{question}

今天的日期：{as_of}

请用 web_search 工具搜索，找出能回答这个问题的真实网页。要求：
1. 必须调用 web_search，不许凭记忆写网址。记忆里的网址大量不存在。
2. 层级要混搭，目标大约：2 个一手来源（官方文档、政府统计、官方发布页）、
   2–3 个新闻报道、2–3 个聚合/百科/教程站。总共 6–8 个。
3. 一手来源优先搜官方域名；新闻搜近期报道；聚合搜 Wikipedia、百科、How-to 站。
4. 每个候选必须来自你刚才搜到的结果。搜不到就少交，不要编。

搜完后，通过 {tool} 工具提交候选列表。"""

RECORD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "query": {"type": "string", "description": "找到它时用的搜索词"},
                    "suggested_tier": {
                        "type": "string",
                        "enum": [Tier.PRIMARY.value, Tier.NEWS.value, Tier.AGGREGATOR.value],
                    },
                },
                "required": ["url", "title", "query", "suggested_tier"],
            },
        }
    },
    "required": ["sources"],
}


def normalize_url(url: str) -> str:
    """去掉 fragment，末尾斜杠统一，便于和搜索结果比对。"""
    cleaned, _ = urldefrag(url.strip())
    if len(cleaned) > 1 and cleaned.endswith("/"):
        cleaned = cleaned[:-1]
    return cleaned


def search_urls_from_content(content: Sequence[Any]) -> set[str]:
    """从 API 响应的 content 块里收集 web_search_result 的 URL。"""
    urls: set[str] = set()
    for block in content:
        data = block if isinstance(block, dict) else _block_dict(block)
        if data.get("type") != "web_search_tool_result":
            continue
        result = data.get("content")
        if not isinstance(result, list):
            continue
        for item in result:
            entry = item if isinstance(item, dict) else _block_dict(item)
            if entry.get("type") == "web_search_result" and entry.get("url"):
                urls.add(normalize_url(str(entry["url"])))
    return urls


def count_searches(content: Sequence[Any]) -> int:
    return sum(1 for block in content if _block_dict(block).get("type") == "server_tool_use")


def filter_to_searched(candidates: Sequence[CandidateSource], searched: set[str]) -> list[CandidateSource]:
    """硬过滤：URL 必须出现在搜索结果里。这是防幻觉的最后一道闸。"""
    kept: list[CandidateSource] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = normalize_url(candidate.url)
        if key not in searched or key in seen:
            continue
        seen.add(key)
        kept.append(candidate)
    return kept


def _block_dict(block: Any) -> dict[str, Any]:
    if isinstance(block, dict):
        return block
    if hasattr(block, "model_dump"):
        return block.model_dump()
    return {"type": getattr(block, "type", None)}


class ClaudeSourceFinder:
    def __init__(
        self,
        client: ClaudeClient,
        *,
        max_searches: int = DEFAULT_MAX_SEARCHES,
        search_tool_type: str = "web_search_20250305",
    ) -> None:
        self._client = client
        self._max_searches = max_searches
        self._search_tool_type = search_tool_type
        self.last_usage = Usage(0, 0, 0)
        self.last_searches = 0

    def find(self, question_text: str, as_of: date) -> list[CandidateSource]:
        prompt = FIND_PROMPT.format(question=question_text, as_of=as_of.isoformat(), tool=RECORD_TOOL)
        tools: list[dict[str, Any]] = [
            {"type": self._search_tool_type, "name": "web_search", "max_uses": self._max_searches},
            {
                "name": RECORD_TOOL,
                "description": "提交从搜索结果里挑出的候选来源",
                "input_schema": RECORD_SCHEMA,
            },
        ]
        try:
            message, requests = self._client.create_message(
                "source_find",
                model=self._client.model,
                max_tokens=4096,
                tools=tools,
                messages=[{"role": "user", "content": prompt}],
            )
        except ClaudeCallError as error:
            self.last_usage = error.usage
            self.last_searches = 0
            detail = str(error).lower()
            # 余额/鉴权问题立刻抛出，让调用方停下；不要当成「这题找不到来源」继续跑。
            if any(token in detail for token in ("credit balance", "insufficient", "authentication", "401", "403")):
                raise
            print(f"❌ [llm] source_find 失败：{error}", file=sys.stderr)
            return []

        content = list(message.content)
        searched = search_urls_from_content(content)
        self.last_searches = count_searches(content)
        self.last_usage = Usage(
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            requests=requests,
        )

        recorded = _recorded_sources(content)
        kept = filter_to_searched(recorded, searched)
        dropped = len(recorded) - len(kept)
        if dropped:
            print(f"[llm] source_find 丢掉 {dropped} 个不在搜索结果里的 URL", file=sys.stderr)
        if not searched:
            print("⚠️  [llm] source_find 响应里没有任何搜索结果", file=sys.stderr)
        return kept


def _recorded_sources(content: Sequence[Any]) -> list[CandidateSource]:
    for block in content:
        data = _block_dict(block)
        if data.get("type") == "tool_use" and data.get("name") == RECORD_TOOL:
            payload = data.get("input") or {}
            return [_candidate(item) for item in payload.get("sources") or []]
    return []


def _candidate(item: dict[str, Any]) -> CandidateSource:
    return CandidateSource(
        url=str(item["url"]),
        title=str(item.get("title") or item["url"]),
        query=str(item.get("query") or ""),
        suggested_tier=Tier(str(item["suggested_tier"])),
    )
