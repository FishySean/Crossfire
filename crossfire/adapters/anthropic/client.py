import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from anthropic import Anthropic, APIConnectionError

from crossfire.domain import Failure, Usage

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1000
TOOL_NAME = "record"
MAX_ATTEMPTS = 2
NETWORK_RETRIES = 2

RETRY_NOTE = """

注意：上一次调用没有返回合法的结构化结果，失败原因是「{error}」。
请重新作答，必须通过 {tool} 工具返回结果，每个必填字段都要给值。"""

# parse 抛出这几类异常，说明模型给的结构不合法，算一次结构化失败。
INVALID_STRUCTURE = (KeyError, TypeError, ValueError)


@dataclass(frozen=True)
class Structured[T]:
    """一次结构化调用的结果。value 和 failure 恰好有一个非空；usage 累计了所有尝试，含请求次数。"""

    value: T | None
    usage: Usage
    failure: Failure | None


class ClaudeClient:
    """用 tool use 强制 Claude 给出结构化输出，并把输出交给 parse 严格转换。

    两层重试互相独立：
    - 网络层：超时和连接错误退避后重试，用尽后照常抛出。
    - 结构层：截断、没有 tool_use、parse 转换失败，带着失败原因重问一次，仍失败就返回 failure，不抛异常。
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = MODEL,
        *,
        client: Any = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client if client is not None else Anthropic(api_key=api_key)
        self.model = model
        self._sleep = sleep

    def call[T](
        self,
        prompt: str,
        schema: dict[str, Any],
        step: str,
        parse: Callable[[dict[str, Any]], T],
        max_tokens: int = MAX_TOKENS,
    ) -> Structured[T]:
        tools = [
            {
                "name": TOOL_NAME,
                "description": f"记录 {step} 步骤的结构化结果",
                "input_schema": schema,
            }
        ]

        input_tokens = output_tokens = requests = 0
        detail = ""
        raw = None

        for attempt in range(MAX_ATTEMPTS):
            text = prompt if attempt == 0 else prompt + RETRY_NOTE.format(error=detail, tool=TOOL_NAME)
            message, sent = self._create(
                step,
                model=self.model,
                max_tokens=max_tokens,
                tools=tools,
                tool_choice={"type": "tool", "name": TOOL_NAME},
                messages=[{"role": "user", "content": text}],
            )
            requests += sent
            input_tokens += message.usage.input_tokens
            output_tokens += message.usage.output_tokens
            raw = json.dumps([block.model_dump() for block in message.content], ensure_ascii=False, default=str)

            tool_blocks = [block for block in message.content if block.type == "tool_use"]
            if message.stop_reason == "max_tokens":
                detail = f"输出被 max_tokens={max_tokens} 截断"
            elif not tool_blocks:
                detail = f"响应里没有 tool_use 块（stop_reason={message.stop_reason}）"
            else:
                try:
                    value = parse(dict(tool_blocks[0].input))
                except INVALID_STRUCTURE as e:
                    detail = f"返回的结构不合法：{type(e).__name__}: {e}"
                else:
                    return Structured(value=value, usage=Usage(input_tokens, output_tokens, requests), failure=None)

            print(f"[llm] {step} 第 {attempt + 1}/{MAX_ATTEMPTS} 次调用失败：{detail}", file=sys.stderr)

        print(f"❌ [llm] {step} 重试后仍然失败，该步结果缺失", file=sys.stderr)
        print(f"❌   失败原因：{detail}", file=sys.stderr)
        print(f"❌   原始输出：{raw}", file=sys.stderr)
        return Structured(
            value=None,
            usage=Usage(input_tokens, output_tokens, requests),
            failure=Failure(step=step, detail=detail, raw=raw),
        )

    def _create(self, step: str, **kwargs: Any) -> tuple[Any, int]:
        """只对超时和连接这类临时性网络错误重试。返回响应和为它实际发出的请求数。

        APITimeoutError 继承自 APIConnectionError，所以捕获后者即可覆盖两者；
        RateLimitError、AuthenticationError、BadRequestError 都在 APIStatusError 分支上，
        不会被这里捕获，仍然照原样往上抛——那些是代码或配置问题，重试只会掩盖 bug。
        """
        for attempt in range(NETWORK_RETRIES + 1):
            try:
                return self._client.messages.create(**kwargs), attempt + 1
            except APIConnectionError as e:
                if attempt == NETWORK_RETRIES:
                    raise
                delay = 2**attempt
                print(
                    f"⚠️  [llm] {step} 遇到网络临时错误 {type(e).__name__}，"
                    f"退避 {delay}s 后第 {attempt + 1}/{NETWORK_RETRIES} 次重试",
                    file=sys.stderr,
                )
                self._sleep(delay)
        raise AssertionError("unreachable")
