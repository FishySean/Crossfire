"""兼容层，第 4 步删除。实现已搬到 crossfire/adapters/anthropic/pairer.py 和 judge.py。这里不许有任何逻辑。"""

from crossfire.adapters.anthropic.judge import JUDGE_MAX_TOKENS, JUDGE_PROMPT, JUDGE_SCHEMA, ClaudeVerdictJudge
from crossfire.adapters.anthropic.pairer import (
    DEFAULT_PAIR_CONCURRENCY,
    PAIR_PROMPT,
    PAIR_SCHEMA,
    RELATION_NAMES,
    ClaudeClaimPairer,
)

__all__ = [
    "DEFAULT_PAIR_CONCURRENCY",
    "JUDGE_MAX_TOKENS",
    "JUDGE_PROMPT",
    "JUDGE_SCHEMA",
    "PAIR_PROMPT",
    "PAIR_SCHEMA",
    "RELATION_NAMES",
    "ClaudeClaimPairer",
    "ClaudeVerdictJudge",
]
