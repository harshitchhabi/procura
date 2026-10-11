from datetime import datetime, timedelta

from os_sim.resource_manager import ResourceManager


def test_allocate_within_capacity_succeeds():
    rm = ResourceManager()
    result = rm.allocate(pid=1, resource="memory", amount=512)
    assert result["success"] is True
    assert rm.available("memory") == 2048 - 512


def test_allocate_over_capacity_rejected():
    rm = ResourceManager()
    result = rm.allocate(pid=1, resource="memory", amount=4096)
    assert result["success"] is False
    assert result["reason"] == "insufficient_capacity"
    # Capacity/allocated state must be unchanged after a rejected request.
    assert rm.allocated["memory"] == 0


def test_release_frees_capacity():
    rm = ResourceManager()
    rm.allocate(pid=1, resource="cpu", amount=50)
    rm.release(pid=1, resource="cpu")
    assert rm.available("cpu") == 100


def test_unknown_resource_raises():
    rm = ResourceManager()
    try:
        rm.allocate(pid=1, resource="gpu", amount=1)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_waits_for_graph_records_conflict():
    rm = ResourceManager()
    rm.allocate(pid=1, resource="database", amount=20)  # take entire pool
    result = rm.allocate(pid=2, resource="database", amount=5)
    assert result["success"] is False
    assert rm.wait_graph() == {"2": [1]}


def test_no_cycle_when_chain_is_linear():
    rm = ResourceManager()
    # pid 2 waits for pid 1, pid 3 waits for pid 2 -- a chain, not a cycle.
    rm.allocate(pid=1, resource="cpu", amount=100)
    rm.allocate(pid=2, resource="cpu", amount=50)  # fails, 2 waits for 1
    rm.allocate(pid=1, resource="memory", amount=2048)
    rm.allocate(pid=3, resource="memory", amount=100)  # fails, 3 waits for 1
    assert rm.detect_cycle() is None


def test_circular_wait_is_detected():
    rm = ResourceManager()
    # pid1 holds cpu, pid2 holds memory. pid1 wants memory (waits for pid2),
    # pid2 wants cpu (waits for pid1) -> classic circular wait.
    rm.allocate(pid=1, resource="cpu", amount=100)
    rm.allocate(pid=2, resource="memory", amount=2048)

    result = rm.allocate(pid=2, resource="cpu", amount=10)
    assert result["success"] is False
    result = rm.allocate(pid=1, resource="memory", amount=10)
    assert result["success"] is False

    cycle = rm.detect_cycle()
    assert cycle is not None
    assert set(cycle) >= {1, 2}


def test_release_all_for_pid_clears_holdings_and_waits():
    rm = ResourceManager()
    rm.allocate(pid=1, resource="cpu", amount=100)
    rm.allocate(pid=2, resource="cpu", amount=10)  # pid2 waits for pid1
    rm.release_all_for_pid(1)
    assert rm.available("cpu") == 100
    # pid1 no longer holds cpu, so the wait edge should be cleared.
    assert 2 not in rm.waits_for or not rm.waits_for[2]


def test_avoidance_mode_denies_unsafe_allocation():
    rm = ResourceManager(avoidance_mode=True)
    rm.register_max_need(1, {"memory": 1000})
    rm.register_max_need(2, {"memory": 2000})
    # Granting 1600 to some third consumer would leave only 448, which is
    # not enough to satisfy either pid1's or pid2's remaining declared need.
    result = rm.allocate(pid=3, resource="memory", amount=1600)
    assert result["success"] is False
    assert result["reason"] == "unsafe_state"


# ---------------------------------------------------------------------------
# Lock-ordering violation checker (lockdep-style)
# Canonical order per RESOURCE_NAMES: cpu < memory < file < database < network
# ---------------------------------------------------------------------------


def test_lock_order_violation_detected_when_acquiring_out_of_order():
    rm = ResourceManager()
    # pid holds 'database' (order 3) then requests 'cpu' (order 0) -- out of order.
    rm.allocate(pid=1, resource="database", amount=5)
    violation = rm.check_lock_order_violation(1, "cpu")
    assert violation is not None
    assert violation["requested"] == "cpu"
    assert "database" in violation["held_out_of_order"]
    assert len(rm.lock_order_log) == 1


def test_no_lock_order_violation_when_acquiring_in_order():
    rm = ResourceManager()
    # pid holds 'cpu' (order 0) then requests 'memory' (order 1) -- in order.
    rm.allocate(pid=1, resource="cpu", amount=10)
    violation = rm.check_lock_order_violation(1, "memory")
    assert violation is None
    assert rm.lock_order_log == []


# ---------------------------------------------------------------------------
# Timeout-based abort
# ---------------------------------------------------------------------------


def test_timeout_based_abort_clears_long_running_wait():
    rm = ResourceManager(timeout_seconds=1.0)
    rm.allocate(pid=1, resource="cpu", amount=100)
    rm.allocate(pid=2, resource="cpu", amount=10)  # pid 2 now waits for pid 1
    assert 2 in rm.waits_for

    # Simulate the wait having started well over timeout_seconds ago.
    rm.wait_since[2] = datetime.now() - timedelta(seconds=5)
    aborted = rm.check_timeouts()

    assert len(aborted) == 1
    assert aborted[0]["pid"] == 2
    assert aborted[0]["action_type"] == "timeout_based_abort"
    assert 2 not in rm.waits_for


def test_timeout_based_abort_does_not_fire_before_timeout():
    rm = ResourceManager(timeout_seconds=30.0)
    rm.allocate(pid=1, resource="cpu", amount=100)
    rm.allocate(pid=2, resource="cpu", amount=10)
    aborted = rm.check_timeouts()
    assert aborted == []
    assert 2 in rm.waits_for
