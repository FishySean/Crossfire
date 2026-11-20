"""call_structured 的特征测试：两层重试、失败返回、token 累加。

被测实现由 structured fixture 提供，断言只认 call_structured 原来的返回形状
（工具入参 + _usage，失败时多一个 _failure）。这组断言先锁住了 llm.call_structured，
搬家期间对旧实现和 ClaudeClient 各跑一遍，旧实现删除后只跑 ClaudeClient，断言没动过。
"""

from types import SimpleNamespace

import anthropic
import httpx
import pytest

from crossfire.adapters.anthropic import ClaudeClient
from crossfire.adapters.anthropic.client import ClaudeCallError
from crossfire.domain import Usage

REQUEST = httpx.Request("POST", "https://api.anthropic.invalid/v1/messages")


def tool_message(data, input_tokens=10, output_tokens=2):
    block = SimpleNamespace(type="tool_use", input=data, model_dump=lambda: {"type": "tool_use", "input": data})
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[block],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def text_message(stop_reason="end_turn", input_tokens=10, output_tokens=2):
    block = SimpleNamespace(type="text", text="不想用工具", model_dump=lambda: {"type": "text", "text": "不想用工具"})
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[block],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def status_error(cls, code):
    return cls(f"HTTP {code}", response=httpx.Response(code, request=REQUEST), body=None)


class ScriptedMessages:
    """按顺序吐出预设的响应；元素是异常就抛出。"""

    def __init__(self, script):
        self.script = list(script)
        self.prompts = []

    def create(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _as_legacy_shape(call):
    """把 ClaudeClient.call 的 Structured 结果还原成 call_structured 的 dict 形状。"""

    def call_structured(prompt, schema, step, max_tokens=1000):
        result = call(prompt, schema, step, parse=lambda data: data, max_tokens=max_tokens)
        shaped = dict(result.value or {})
        # call_structured 的 _usage 只有两个 token 键；请求数是第 3 步加的，单独在下面的测试里验。
        shaped["_usage"] = {"input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens}
        if result.failure is not None:
            shaped["_failure"] = result.failure.to_dict()
        return shaped

    return call_structured


@pytest.fixture
def structured():
    """返回 (call, messages, sleeps)。call 的签名和返回形状与原来的 llm.call_structured 一致。"""
    sleeps = []

    def install(script):
        messages = ScriptedMessages(script)
        client = ClaudeClient(client=SimpleNamespace(messages=messages), sleep=sleeps.append)
        return _as_legacy_shape(client.call), messages, sleeps

    return install


SCHEMA = {"type": "object", "properties": {"x": {"type": "number"}}, "required": ["x"]}


@pytest.mark.parametrize(
    "error",
    [anthropic.APIConnectionError(request=REQUEST), anthropic.APITimeoutError(request=REQUEST)],
    ids=["connection", "timeout"],
)
def test_network_errors_retry_twice_with_backoff(structured, error, capsys):
    call, messages, sleeps = structured([error, error, tool_message({"x": 1})])
    result = call("问题", SCHEMA, "pair")

    assert result["x"] == 1
    assert "_failure" not in result
    assert len(messages.prompts) == 3
    assert sleeps == [1, 2]
    assert capsys.readouterr().err.count("⚠️") == 2


def test_network_errors_raise_after_retries_are_exhausted(structured):
    error = anthropic.APITimeoutError(request=REQUEST)
    call, messages, sleeps = structured([error, error, error])
    # 第 5b 步有意修改：pytest.raises(anthropic.APITimeoutError) → ClaudeCallError，原异常在 error 里。
    # 原因：backlog「比对抛异常时请求数记成 0」，异常要带出已经发出的请求数。
    with pytest.raises(ClaudeCallError) as caught:
        call("问题", SCHEMA, "pair")
    assert caught.value.error is error and caught.value.__cause__ is error
    assert caught.value.usage.requests == 3
    assert len(messages.prompts) == 3
    assert sleeps == [1, 2]


@pytest.mark.parametrize(
    "error",
    [
        status_error(anthropic.AuthenticationError, 401),
        status_error(anthropic.BadRequestError, 400),
        status_error(anthropic.RateLimitError, 429),
    ],
    ids=["auth", "bad-request", "rate-limit"],
)
def test_other_api_errors_raise_immediately(structured, error):
    call, messages, sleeps = structured([error])
    # 第 5b 步有意修改：pytest.raises(type(error)) → ClaudeCallError，原因同上。
    with pytest.raises(ClaudeCallError) as caught:
        call("问题", SCHEMA, "pair")
    assert caught.value.error is error
    assert caught.value.usage.requests == 1
    assert len(messages.prompts) == 1
    assert sleeps == []


def test_an_error_after_a_structural_retry_carries_both_requests_and_the_tokens_spent():
    messages = ScriptedMessages([text_message(input_tokens=5, output_tokens=1), status_error(anthropic.BadRequestError, 400)])
    client = ClaudeClient(client=SimpleNamespace(messages=messages), sleep=lambda delay: None)
    with pytest.raises(ClaudeCallError) as caught:
        client.call("问题", SCHEMA, "pair", parse=lambda data: data)
    assert caught.value.usage == Usage(5, 1, 2)


@pytest.mark.parametrize(
    ("first", "detail_fragment"),
    [(text_message(stop_reason="max_tokens"), "max_tokens=1000"), (text_message(), "没有 tool_use")],
    ids=["truncated", "no-tool-use"],
)
def test_structural_failure_retries_once_with_the_reason(structured, first, detail_fragment):
    call, messages, sleeps = structured([first, tool_message({"x": 2})])
    result = call("原始问题", SCHEMA, "extract")

    assert result["x"] == 2
    assert len(messages.prompts) == 2
    assert messages.prompts[0] == "原始问题"
    assert messages.prompts[1].startswith("原始问题")
    assert detail_fragment in messages.prompts[1]
    assert sleeps == []


def test_both_attempts_failing_returns_failure_instead_of_raising(structured, capsys):
    call, messages, _ = structured([text_message(stop_reason="max_tokens"), text_message(stop_reason="max_tokens")])
    result = call("问题", SCHEMA, "judge", max_tokens=3000)

    assert len(messages.prompts) == 2
    assert set(result) == {"_usage", "_failure"}
    assert result["_failure"]["step"] == "judge"
    assert "max_tokens=3000" in result["_failure"]["detail"]
    assert result["_failure"]["raw"]
    assert "❌" in capsys.readouterr().err


def test_usage_accumulates_across_attempts(structured):
    call, _, _ = structured(
        [text_message(input_tokens=100, output_tokens=7), tool_message({"x": 3}, input_tokens=120, output_tokens=9)]
    )
    assert call("问题", SCHEMA, "pair")["_usage"] == {"input_tokens": 220, "output_tokens": 16}


def test_usage_of_a_failed_call_is_still_reported(structured):
    call, _, _ = structured([text_message(input_tokens=5, output_tokens=1), text_message(input_tokens=6, output_tokens=1)])
    assert call("问题", SCHEMA, "pair")["_usage"] == {"input_tokens": 11, "output_tokens": 2}


# ---- 请求次数：两层重试都要算进去 ----


def _requests(script):
    messages = ScriptedMessages(script)
    client = ClaudeClient(client=SimpleNamespace(messages=messages), sleep=lambda delay: None)
    result = client.call("问题", SCHEMA, "pair", parse=lambda data: data)
    assert result.usage.requests == len(messages.prompts), "requests 必须等于真正调用 messages.create 的次数"
    return result.usage.requests


def test_one_clean_call_is_one_request():
    assert _requests([tool_message({"x": 1})]) == 1


def test_network_retries_count_as_requests():
    error = anthropic.APITimeoutError(request=REQUEST)
    assert _requests([error, error, tool_message({"x": 1})]) == 3


def test_structural_retry_counts_as_a_request():
    assert _requests([text_message(), tool_message({"x": 1})]) == 2


def test_both_layers_add_up_even_when_the_call_finally_fails():
    error = anthropic.APIConnectionError(request=REQUEST)
    assert _requests([error, text_message(), error, error, text_message()]) == 5
