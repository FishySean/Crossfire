"""临时的组装点：把 Steel 和 Claude 的实现拼成 pipeline.run 需要的四个依赖。

这里是临时位置。第 4 步建真正的组合根（composition root，全程序唯一负责组装零件的地方）时，
这个文件整体挪过去，读环境变量和 .env 也一并集中到那里。在那之前，只有入口（scripts/verify.py、
web/server.py）可以 import 这个模块；业务代码不许 import 它。
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from crossfire.adapters.anthropic import ClaudeClaimExtractor, ClaudeClaimPairer, ClaudeClient, ClaudeVerdictJudge
from crossfire.adapters.anthropic.pairer import DEFAULT_PAIR_CONCURRENCY
from crossfire.adapters.steel import CACHE_ROOT, CachedPageFetcher, SteelPageFetcher
from crossfire.application.ports import ClaimExtractor, ClaimPairer, PageFetcher, VerdictJudge
from crossfire.domain import Mode


@dataclass(frozen=True)
class Dependencies:
    fetcher: PageFetcher
    extractor: ClaimExtractor
    pairer: ClaimPairer
    judge: VerdictJudge


def build_default_dependencies(
    mode: Mode,
    question_id: str,
    *,
    anthropic_api_key: str | None = None,
    steel_api_key: str | None = None,
    pair_concurrency: int = DEFAULT_PAIR_CONCURRENCY,
) -> Dependencies:
    """key 不传时从环境变量和 .env 读。缓存按问题分目录存放，所以要 question_id。"""
    load_dotenv()
    claude = ClaudeClient(anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"))
    fetcher: PageFetcher
    if mode is Mode.CACHED:
        fetcher = CachedPageFetcher(CACHE_ROOT / question_id)
    else:
        fetcher = SteelPageFetcher(steel_api_key or os.environ.get("STEEL_API_KEY"))
    return Dependencies(
        fetcher=fetcher,
        extractor=ClaudeClaimExtractor(claude),
        pairer=ClaudeClaimPairer(claude, concurrency=pair_concurrency),
        judge=ClaudeVerdictJudge(claude),
    )
