# python_engine/bounded_queue.py
import threading
from collections import deque
from typing import Any, Optional

class BoundedQueue:
    def __init__(self, maxsize: Optional[int] = None):
        if maxsize is not None and maxsize <= 0:
            raise ValueError("maxsize must be positive or None for unbounded")
        self._queue = deque()
        self._maxsize = maxsize
        self._lock = threading.Lock()
        self._not_full = threading.Condition(self._lock)
        self._not_empty = threading.Condition(self._lock)
        self._closed = False

    def put(self, item: Any) -> None:
        with self._not_full:
            while (self._maxsize is not None and 
                   len(self._queue) == self._maxsize and 
                   not self._closed):
                self._not_full.wait()
            if self._closed:
                raise RuntimeError("Queue is closed; cannot put")
            self._queue.append(item)
            self._not_empty.notify()

    def get(self) -> Any:
        with self._not_empty:
            while len(self._queue) == 0 and not self._closed:
                self._not_empty.wait()
            if self._closed and len(self._queue) == 0:
                raise RuntimeError("Queue is closed and drained")
            item = self._queue.popleft()
            self._not_full.notify()
            return item

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            self._not_full.notify_all()
            self._not_empty.notify_all()

    def __len__(self) -> int:
        return len(self._queue)