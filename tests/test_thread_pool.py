import pytest
import threading
import time
from python_engine.thread_pool import ThreadPool  # ✅ FIXED IMPORT
from functools import partial

def test_partial_callable():
    """A functools.partial must run successfully and not kill the worker."""
    pool = ThreadPool(num_workers=1)
    results = []
    lock = threading.Lock()

    def add_to_list(lst, val):
        with lock:
            lst.append(val)

    # Submit a partial – this used to crash the worker
    pool.submit(partial(add_to_list, results, 42))
    pool.shutdown()

    assert results == [42]
    # Ensure the worker survived (active_count would be 0 after shutdown)
    assert pool.active_count == 0

def test_basic_task_execution():
    """Submit one task, verify it runs."""
    pool = ThreadPool(num_workers=1)
    results = []

    def task():
        results.append("done")

    pool.submit(task)
    pool.shutdown()

    assert results == ["done"]


def test_multiple_tasks():
    """Submit 100 tasks, verify all run."""
    pool = ThreadPool(num_workers=4)
    results = []
    lock = threading.Lock()

    def task(i):
        with lock:
            results.append(i)

    for i in range(100):
        pool.submit(task, i)

    pool.shutdown()

    assert len(results) == 100
    assert sorted(results) == list(range(100))


def test_task_exception_handling():
    """A failing task doesn't kill the pool."""
    pool = ThreadPool(num_workers=1)
    results = []

    def bad_task():
        raise ValueError("Intentional failure")

    def good_task():
        results.append("good")

    pool.submit(bad_task)
    pool.submit(good_task)
    pool.shutdown()

    assert results == ["good"]


def test_shutdown_with_work_in_progress():
    """shutdown() must wait for in-flight work to complete."""
    pool = ThreadPool(num_workers=2)
    results = []
    lock = threading.Lock()
    start_time = time.time()

    def slow_task():
        time.sleep(0.5)
        with lock:
            results.append("done")

    for _ in range(5):
        pool.submit(slow_task)

    pool.shutdown()
    elapsed = time.time() - start_time

    assert elapsed >= 0.5
    assert len(results) == 5


def test_context_manager():
    """'with' statement should auto-shutdown the pool."""
    results = []

    with ThreadPool(num_workers=2) as pool:
        for _ in range(10):
            # Appending a constant 1 is safe – no late‑binding closure trap.
            pool.submit(lambda: results.append(1))

    assert len(results) == 10


def test_submit_after_shutdown_raises():
    """Cannot submit tasks after shutdown."""
    pool = ThreadPool(num_workers=1)
    pool.shutdown()

    with pytest.raises(RuntimeError, match="shutting down"):
        pool.submit(lambda: None)


def test_deadlock_stress():
    """Heavy concurrent usage should not deadlock."""
    pool = ThreadPool(num_workers=4)
    results = []
    lock = threading.Lock()
    tasks_per_producer = 50
    num_producers = 10

    def producer(producer_id):
        # ✅ FIXED: define a real function, not a lambda with a statement
        def submit_task(pid, j):
            with lock:
                results.append(f"P{pid}-{j}")

        for j in range(tasks_per_producer):
            pool.submit(submit_task, producer_id, j)

    producers = []
    for i in range(num_producers):
        t = threading.Thread(target=producer, args=(i,))
        t.start()
        producers.append(t)

    for t in producers:
        t.join()

    pool.shutdown()

    expected_total = num_producers * tasks_per_producer
    assert len(results) == expected_total

def test_shutdown_unblocks_blocked_submit():
    """
    Regression test: when a bounded queue is full, a blocked submit()
    must be unblocked by shutdown() without deadlocking.
    """
    pool = ThreadPool(num_workers=1, queue_maxsize=1)

    # ---- Step 1: keep the worker busy with a task that blocks ----
    slow_lock = threading.Lock()
    slow_lock.acquire()          # worker will block here
    slow_started = threading.Event()

    def slow():
        slow_started.set()
        with slow_lock:          # blocks until we release
            time.sleep(0.1)

    pool.submit(slow)
    slow_started.wait()          # worker is now executing slow task

    # ---- Step 2: fill the queue (worker is busy, so this stays queued) ----
    pool.submit(lambda: None)    # now queue has 1 item (maxsize=1 → full)

    # ---- Step 3: submit a third task – it will block on put() ----
    third_done = threading.Event()
    exception_raised = False

    def submitter():
        nonlocal exception_raised
        try:
            pool.submit(lambda: None)
        except RuntimeError as e:
            if "shutting down" in str(e):
                exception_raised = True
        third_done.set()

    t = threading.Thread(target=submitter)
    t.start()

    # Give the submitter time to enter the blocking put().
    time.sleep(0.05)

    # ---- Step 4: shutdown – unblocks the blocked submit ----
    pool.shutdown(wait=False)    # sets flag + closes queue

    # Release the slow lock so the worker can finish after the test.
    slow_lock.release()

    # ---- Step 5: verify ----
    t.join(timeout=1.0)
    assert not t.is_alive(), "Submitter thread hung"
    assert third_done.is_set()
    assert exception_raised, "Blocked submit did not raise RuntimeError"

    # Clean up
    pool.shutdown(wait=True, timeout=1.0)
    assert pool.active_count == 0