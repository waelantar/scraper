# python_engine/thread_pool.py
import threading
import logging
import time
from typing import Callable, Any, Optional, List

from python_engine.bounded_queue import BoundedQueue

logger = logging.getLogger(__name__)

def _callable_name(func: Callable) -> str:
    return getattr(func, "__name__", repr(func))


class ThreadPool:
    def __init__(self, num_workers: int, queue_maxsize: Optional[int] = None):
        if num_workers <= 0:
            raise ValueError("num_workers must be positive")
        self._num_workers = num_workers
        self._task_queue = BoundedQueue(maxsize=queue_maxsize)
        self._shutdown_event = threading.Event()
        self._workers: List[threading.Thread] = []
        self._lock = threading.Lock()

        self._start_workers()

    def _start_workers(self) -> None:
        with self._lock:
            for i in range(self._num_workers):
                t = threading.Thread(
                    target=self._worker_loop,
                    name=f"PoolWorker-{i+1}",
                    daemon=False,
                )
                t.start()
                self._workers.append(t)

    def _worker_loop(self) -> None:
        while True:
            try:
                func, args, kwargs = self._task_queue.get()
            except RuntimeError:
                logger.debug(f"{threading.current_thread().name} exiting (queue drained)")
                break

            func_repr = _callable_name(func)
            try:
                func(*args, **kwargs)
            except Exception as e:
                try:
                    logger.error(f"Task {func_repr} failed: {e}", exc_info=True)
                except Exception:
                    print(f"CRITICAL: Task {func_repr} failed and logging failed: {e}")

        logger.info(f"{threading.current_thread().name} stopped")

    def submit(self, func: Callable, *args, **kwargs) -> None:
        # Fast path: check flag without holding any lock.
        if self._shutdown_event.is_set():
            raise RuntimeError("Cannot submit: pool is shutting down")

        try:
            # Let the queue handle the blocking; we hold no lock here.
            self._task_queue.put((func, args, kwargs))
        except RuntimeError as e:
            # If the queue is closed (race with shutdown), translate the error.
            if self._shutdown_event.is_set():
                raise RuntimeError("Cannot submit: pool is shutting down") from None
            raise

        logger.debug(f"Submitted {_callable_name(func)}")

    def shutdown(self, wait: bool = True, timeout: Optional[float] = None) -> None:
        # Atomically close the queue and set the flag.
        # These are non‑blocking, so holding the lock is safe.
        with self._lock:
            self._shutdown_event.set()
            self._task_queue.shutdown()

        if not wait:
            return

        # Snapshot workers while holding lock, then release before joining.
        with self._lock:
            workers = self._workers[:]

        start_time = time.time() if timeout is not None else None
        for t in workers:
            remaining = None
            if timeout is not None and start_time is not None:
                elapsed = time.time() - start_time
                remaining = timeout - elapsed
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for workers")
            t.join(timeout=remaining)
            if t.is_alive():
                raise TimeoutError(f"Worker {t.name} did not exit")

        with self._lock:
            self._workers.clear()

        logger.info("Thread pool shut down successfully")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown(wait=True)

    @property
    def active_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._workers if t.is_alive())

    @property
    def task_count(self) -> int:
        return len(self._task_queue)