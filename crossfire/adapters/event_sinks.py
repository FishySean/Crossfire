from collections.abc import Callable
from typing import Any

from crossfire.application.events import Event


class CallbackEventSink:
    """把事件转成 dict 交给回调，比如 web 端塞进 SSE 队列。"""

    def __init__(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._callback = callback

    def emit(self, event: Event) -> None:
        self._callback(event.to_dict())


class NullEventSink:
    """没人收事件时用它，业务代码就不用到处判断有没有 sink。"""

    def emit(self, event: Event) -> None:
        pass
