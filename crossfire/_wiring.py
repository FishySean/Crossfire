"""临时的组装点，只为还没迁到组合根的 web/server.py 保留，第 4 步后面的提交删掉。

配置已经改从 Settings 读，这里不再碰 .env 和环境变量。
"""

from dataclasses import dataclass

from crossfire.adapters.anthropic import ClaudeClaimExtractor, ClaudeClient, ClaudeVerdictJudge
from crossfire.adapters.steel import CachedPageFetcher, SteelPageFetcher
from crossfire.application.ports import ClaimExtractor, ClaimPairer, PageFetcher, VerdictJudge
from crossfire.composition import KEYS_FOR_MODE, build_pairer
from crossfire.config import Settings
from crossfire.domain import Mode


@dataclass(frozen=True)
class Dependencies:
    fetcher: PageFetcher
    extractor: ClaimExtractor
    pairer: ClaimPairer
    judge: VerdictJudge


def build_default_dependencies(mode: Mode, question_id: str, *, settings: Settings | None = None) -> Dependencies:
    settings = settings or Settings.from_env()
    settings.require(*KEYS_FOR_MODE[mode])
    fetcher: PageFetcher
    if mode is Mode.CACHED:
        fetcher = CachedPageFetcher(settings.cache_dir / question_id)
    else:
        fetcher = SteelPageFetcher(settings.steel_api_key)
    return Dependencies(
        fetcher=fetcher,
        extractor=ClaudeClaimExtractor(ClaudeClient(settings.anthropic_api_key, settings.model_extract)),
        pairer=build_pairer(settings),
        judge=ClaudeVerdictJudge(ClaudeClient(settings.anthropic_api_key, settings.model_judge)),
    )
