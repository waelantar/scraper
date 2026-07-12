import pytest
import threading
import time
from python_engine.bounded_queue import BoundedQueue


def test_put_and_get_single():
    """Test: put one item, get it back."""
    q = BoundedQueue(maxsize=1)
    q.put("apple")
    assert q.get() == "apple"

def test_fifo_order():
    """Test: Queue respects First-In-First-Out order."""
    q = BoundedQueue(maxsize=3)
    q.put(1)
    q.put(2)
    q.put(3)
    assert q.get() == 1
    assert q.get() == 2
    assert q.get() == 3

def test_put_blocks_when_full():
    """Test: put() blocks when maxsize is reached, until space frees."""
    q = BoundedQueue(maxsize=1)
    q.put("first")
    
    start = time.time()
    
    def delayed_pop():
        time.sleep(0.1)
        q.get()
    
    threading.Thread(target=delayed_pop, daemon=True).start()
    
    # This should block for ~0.1 seconds
    q.put("second")
    elapsed = time.time() - start
    
    assert elapsed >= 0.1
    assert q.get() == "second"

def test_get_blocks_when_empty():
    """Test: get() blocks when empty, until an item is added."""
    q = BoundedQueue(maxsize=1)
    start = time.time()
    
    def delayed_put():
        time.sleep(0.1)
        q.put("wake up!")
    
    threading.Thread(target=delayed_put, daemon=True).start()
    
    # This should block for ~0.1 seconds
    item = q.get()
    elapsed = time.time() - start
    
    assert elapsed >= 0.1
    assert item == "wake up!"


def test_shutdown_drains_remaining_items():
    """At shutdown, get() must return leftovers, then raise."""
    q = BoundedQueue(maxsize=3)
    q.put("one")
    q.put("two")
    q.shutdown()
    
    # Should drain the two items first
    assert q.get() == "one"
    assert q.get() == "two"
    
    # Then raise on the next call
    with pytest.raises(RuntimeError, match="closed and drained"):
        q.get()

def test_shutdown_wakes_blocked_consumers():
    """
    Consumers blocked on empty should wake up and exit cleanly
    when shutdown() is called.
    """
    q = BoundedQueue(maxsize=2)
    
    results = []
    
    def consumer():
        try:
            q.get()
        except RuntimeError:
            results.append("exited")
    
    # Start 2 consumers that will block on empty
    threads = []
    for _ in range(2):
        t = threading.Thread(target=consumer)
        t.start()
        threads.append(t)
    
    # Give them a moment to actually enter wait()
    time.sleep(0.05)
    
    # Shutdown should wake them both
    q.shutdown()
    
    for t in threads:
        t.join(timeout=1.0)
    
    assert results == ["exited", "exited"]

def test_shutdown_prevents_new_puts():
    """After shutdown, put() should raise immediately."""
    q = BoundedQueue(maxsize=3)
    q.shutdown()
    
    with pytest.raises(RuntimeError, match="Queue is closed"):
        q.put("should not go in")


def test_four_producers_four_consumers():
    """
    The classic stress test:
    - 4 producers, each pushing 250 items (total 1000).
    - 4 consumers, all pulling into a shared list.
    - Queue maxsize=3 to force blocking.
    - Verify all 1000 items arrive exactly once.
    """
    q = BoundedQueue(maxsize=3)
    results = []
    results_lock = threading.Lock()
    
    # Producer function (NO unused lock param)
    def producer(prod_id: int, count: int):
        for i in range(count):
            q.put(f"P{prod_id}-{i}")
    
    # Consumer function
    def consumer():
        while True:
            try:
                item = q.get()
                with results_lock:
                    results.append(item)
            except RuntimeError:
                # Queue is drained and closed - exit safely
                break
    
    # Start 4 producers
    producers = []
    for pid in range(4):
        t = threading.Thread(target=producer, args=(pid, 250))
        t.start()
        producers.append(t)
    
    # Start 4 consumers
    consumers = []
    for _ in range(4):
        t = threading.Thread(target=consumer)
        t.start()
        consumers.append(t)
    
    # Wait for all producers to finish
    for t in producers:
        t.join()
    
    # Signal that no more items will ever be added
    q.shutdown()
    
    # Wait for all consumers to finish draining
    for t in consumers:
        t.join()
    
    # --- VERIFICATION ---
    # 1. We must have exactly 1000 items
    assert len(results) == 1000, f"Expected 1000, got {len(results)}"
    
    # 2. Extract the numbers (P0-0, P0-1, ... P3-249)
    numbers = [int(item.split('-')[1]) for item in results]
    
    # 3. The sum of 0..249 repeated 4 times should be:
    expected_sum = sum(range(250)) * 4  # 124,500
    assert sum(numbers) == expected_sum, f"Sum mismatch: {sum(numbers)} vs {expected_sum}"
    
    # 4. Ensure every number 0-249 appears exactly 4 times (one per producer)
    from collections import Counter
    counts = Counter(numbers)
    for i in range(250):
        assert counts[i] == 4, f"Number {i} appeared {counts[i]} times, expected 4"

def test_deadlock_stress_maxsize_1():
    """
    Brutal stress test with maxsize=1 to force the exact scenario
    where a notify() could wake the wrong thread type if we used one Condition.
    """
    q = BoundedQueue(maxsize=1)
    results = []
    lock = threading.Lock()
    rounds = 200

    def producer():
        for i in range(rounds):
            q.put(f"P-{i}")

    def consumer(consumer_id: int):
        while True:
            try:
                item = q.get()
                with lock:
                    results.append(item)
            except RuntimeError:
                # Queue is drained and closed - exit cleanly
                break

    threads = []

    # Start 1 Producer
    t = threading.Thread(target=producer)
    t.start()
    threads.append(t)

    # Start 3 Consumers
    for i in range(3):
        t = threading.Thread(target=consumer, args=(i,))
        t.start()
        threads.append(t)

    # 1. Wait for the producer to FINISH pushing all items
    producer_thread = threads[0]
    producer_thread.join(timeout=5.0)
    assert not producer_thread.is_alive(), "Producer hung!"

    # 2. SIGNAL that no more items are coming.
    #    This wakes all consumers and tells them to exit once empty.
    q.shutdown()

    # 3. Now wait for the consumers to finish draining.
    #    They will wake up from shutdown(), drain leftovers, and raise RuntimeError to exit.
    consumer_threads = threads[1:]
    for t in consumer_threads:
        t.join(timeout=5.0)
        assert not t.is_alive(), f"Consumer {t.name} hung!"

    # 4. Verify we got exactly 'rounds' items
    assert len(results) == rounds, f"Expected {rounds}, got {len(results)}"
    
    # Verify no duplicates/lost numbers
    numbers = [int(item.split('-')[1]) for item in results]
    expected_sum = sum(range(rounds))
    assert sum(numbers) == expected_sum
        
if __name__ == "__main__":
    # This allows `python tests/test_queue.py` to run the big test manually
    test_four_producers_four_consumers()
    print("✅ All acceptance tests passed!")