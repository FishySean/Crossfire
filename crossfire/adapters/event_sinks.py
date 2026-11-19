import queue
from collections.abc import Callable
from typing import Any

from crossfire.application.events import Event


class CallbackEventSink:
    """把事件转成 dict 交给回调。"""

    def __init__(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._callback = callback

    def emit(self, event: Event) -> None:
        self._callback(event.to_dict())


class QueueEventSink:
    """把事件转成 dict 放进线程安全的队列。web 端在后台线程里跑用例，SSE 生成器从队列里取。"""

    def __init__(self, events: "queue.Queue[Any]") -> None:
        self._events = events

    def emit(self, event: Event) -> None:
        self._events.put(event.to_dict())


class NullEventSink:
    """没人收事件时用它，业务代码就不用到处判断有没有 sink。"""

    def emit(self, event: Event) -> None:
        pass
