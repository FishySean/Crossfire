import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


class ThreadTicker:
    """每次 every 开一个守护线程计时，stop 会等线程退出，所以 stop 返回后不会再有 tick。"""

    def every(self, seconds: float, tick: Callable[[], None]) -> Callable[[], None]:
        stopped = threading.Event()

        def beat() -> None:
            while not stopped.wait(seconds):
                tick()

        thread = threading.Thread(target=beat, daemon=True)
        thread.start()

        def stop() -> None:
            stopped.set()
            thread.join()

        return stop
