"""兼容层，第 4 步删除。实现已搬到 crossfire/adapters/anthropic/client.py。这里不许有任何逻辑。"""

from crossfire.adapters.anthropic.client import (
    MAX_ATTEMPTS,
    MAX_TOKENS,
    MODEL,
    NETWORK_RETRIES,
    RETRY_NOTE,
    TOOL_NAME,
    ClaudeClient,
    Structured,
)

__all__ = [
    "MAX_ATTEMPTS",
    "MAX_TOKENS",
    "MODEL",
    "NETWORK_RETRIES",
    "RETRY_NOTE",
    "TOOL_NAME",
    "ClaudeClient",
    "Structured",
]
