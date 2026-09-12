import json
import os
import sys

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1000
TOOL_NAME = "record"
MAX_ATTEMPTS = 2

RETRY_NOTE = """

注意：上一次调用没有返回合法的结构化结果，失败原因是「{error}」。
请重新作答，必须通过 {tool} 工具返回结果，每个必填字段都要给值。"""


def call_structured(prompt: str, schema: dict, step: str, max_tokens: int = MAX_TOKENS) -> dict:
    """调用 Claude 并用 tool use 强制结构化输出。

    返回工具入参本身，外加两个保留键：`_usage` 始终存在，`_failure` 仅在重试后仍失败时存在。
    """
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    tools = [
        {
            "name": TOOL_NAME,
            "description": f"记录 {step} 步骤的结构化结果",
            "input_schema": schema,
        }
    ]

    usage = {"input_tokens": 0, "output_tokens": 0}
    detail = None
    raw = None

    for attempt in range(MAX_ATTEMPTS):
        text = prompt if attempt == 0 else prompt + RETRY_NOTE.format(error=detail, tool=TOOL_NAME)
        message = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{"role": "user", "content": text}],
        )
        usage["input_tokens"] += message.usage.input_tokens
        usage["output_tokens"] += message.usage.output_tokens
        raw = json.dumps([block.model_dump() for block in message.content], ensure_ascii=False, default=str)

        tool_blocks = [block for block in message.content if block.type == "tool_use"]
        if message.stop_reason == "max_tokens":
            detail = f"输出被 max_tokens={max_tokens} 截断"
        elif not tool_blocks:
            detail = f"响应里没有 tool_use 块（stop_reason={message.stop_reason}）"
        else:
            result = dict(tool_blocks[0].input)
            result["_usage"] = usage
            return result

        print(f"[llm] {step} 第 {attempt + 1}/{MAX_ATTEMPTS} 次调用失败：{detail}", file=sys.stderr)

    print(f"❌ [llm] {step} 重试后仍然失败，该步结果缺失", file=sys.stderr)
    print(f"❌   失败原因：{detail}", file=sys.stderr)
    print(f"❌   原始输出：{raw}", file=sys.stderr)
    return {"_usage": usage, "_failure": {"step": step, "detail": detail, "raw": raw}}
