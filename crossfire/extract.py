"""兼容层，第 4 步删除。实现已搬到 crossfire/adapters/anthropic/extractor.py。这里不许有任何逻辑。"""

from crossfire.adapters.anthropic.extractor import (
    EXTRACT_PROMPT,
    EXTRACT_SCHEMA,
    MAX_CONTENT_CHARS,
    ClaudeClaimExtractor,
)

__all__ = ["EXTRACT_PROMPT", "EXTRACT_SCHEMA", "MAX_CONTENT_CHARS", "ClaudeClaimExtractor"]
