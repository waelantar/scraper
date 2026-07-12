import threading
from collections import deque
from typing import Any

class BoundedQueue:
    """
    A multi-producer, multi-consumer thread-safe queue with a maximum size.
    Uses TWO Condition variables (not_full, not_empty) sharing ONE lock.
    This prevents the "lost wakeup" bug where a notify() meant for a producer
    is consumed by a consumer (and vice versa).
    """
    def __init__(self, maxsize: int):
        if maxsize <= 0:
            raise ValueError("maxsize must be positive")
        
        self._queue = deque()
        self._maxsize = maxsize
        self._closed = False
        
        # ONE lock to protect the shared state
        self._lock = threading.Lock()
        
        # TWO waiting rooms attached to the SAME lock
        self._not_full = threading.Condition(self._lock)   # Producers wait here
        self._not_empty = threading.Condition(self._lock)  # Consumers wait here

    def put(self, item: Any) -> None:
        """Add an item. Blocks if full. Raises if closed."""
        with self._not_full:  # Acquire the shared lock
            # Wait while full AND not closed
            while len(self._queue) == self._maxsize and not self._closed:
                self._not_full.wait()  # Release lock, sleep in Room A
            
            if self._closed:
                raise RuntimeError("Queue is closed; cannot put")
            
            self._queue.append(item)
            # Wake exactly ONE consumer waiting in Room B
            self._not_empty.notify()

    def get(self) -> Any:
        """Remove and return an item. Blocks if empty. Raises if closed & drained."""
        with self._not_empty:  # Acquire the shared lock
            # Wait while empty AND not closed
            while len(self._queue) == 0 and not self._closed:
                self._not_empty.wait()  # Release lock, sleep in Room B
            
            if self._closed and len(self._queue) == 0:
                raise RuntimeError("Queue is closed and drained")
            
            item = self._queue.popleft()
            # Wake exactly ONE producer waiting in Room A
            self._not_full.notify()
            return item

    def shutdown(self) -> None:
        """Stop accepting new items. Drain leftovers, then raise on next get."""
        with self._lock:  # Grab the shared lock directly
            self._closed = True
            # Wake up ALL producers AND ALL consumers so they can re-check
            self._not_full.notify_all()
            self._not_empty.notify_all()