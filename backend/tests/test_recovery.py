from os_sim import process_manager
from os_sim.resource_manager import ResourceManager
from recovery.detector import detect_deadlock, detect_memory_failure, run_detection
from recovery.recovery import recover_memory_failure, recover_deadlock


def test_detect_memory_failure_flags_oversized_request():
    rm = ResourceManager()
    rm.allocate(pid=1, resource="memory", amount=1800)
    proc = {"pid": 2, "memory_requirement": 500}
    finding = detect_memory_failure(proc, rm)
    assert finding is not None
    assert finding["error_type"] == "memory_failure"


def test_detect_memory_failure_none_when_available():
    rm = ResourceManager()
    proc = {"pid": 1, "memory_requirement": 500}
    assert detect_memory_failure(proc, rm) is None


def test_detect_deadlock_flags_cycle():
    rm = ResourceManager()
    rm.allocate(pid=1, resource="cpu", amount=100)
    rm.allocate(pid=2, resource="memory", amount=2048)
    rm.allocate(pid=2, resource="cpu", amount=10)  # 2 waits for 1
    rm.allocate(pid=1, resource="memory", amount=10)  # 1 waits for 2
    finding = detect_deadlock(rm)
    assert finding is not None
    assert finding["error_type"] == "deadlock"


def test_detect_deadlock_none_for_non_circular_wait():
    rm = ResourceManager()
    rm.allocate(pid=1, resource="cpu", amount=100)
    rm.allocate(pid=2, resource="cpu", amount=10)  # 2 waits for 1, no cycle
    assert detect_deadlock(rm) is None


def test_run_detection_finds_memory_failure_for_real_process():
    rm = ResourceManager()
    rm.allocate(pid=999, resource="memory", amount=2000)
    proc = process_manager.create_process(name="Big task", burst_time=10, memory_requirement=500)
    findings = run_detection([proc], rm)
    types = {f["error_type"] for f in findings}
    assert "memory_failure" in types


def test_recover_memory_failure_suspends_lowest_priority_holder():
    rm = ResourceManager()
    low = process_manager.create_process(name="Low prio holder", burst_time=5, priority="Low", memory_requirement=1800)
    process_manager.start_process(low["pid"])
    rm.allocate(low["pid"], "memory", 1800)

    failing = process_manager.create_process(name="Needs memory", burst_time=5, priority="High", memory_requirement=500)

    finding = {"error_type": "memory_failure", "pid": failing["pid"], "details": "test"}
    action = recover_memory_failure(finding, rm)

    assert action["target_pid"] == low["pid"]
    refreshed_low = process_manager.get_process(low["pid"])
    assert refreshed_low["state"] == "BLOCKED"
    # Memory should now be available for the failing process's requirement.
    assert rm.available("memory") >= 500


def test_recover_deadlock_terminates_lowest_priority_in_cycle():
    rm = ResourceManager()
    p1 = process_manager.create_process(name="P1", burst_time=5, priority="High", memory_requirement=0)
    p2 = process_manager.create_process(name="P2", burst_time=5, priority="Low", memory_requirement=0)
    process_manager.start_process(p1["pid"])
    process_manager.start_process(p2["pid"])

    rm.allocate(p1["pid"], "cpu", 100)
    rm.allocate(p2["pid"], "memory", 2048)
    rm.allocate(p2["pid"], "cpu", 10)
    rm.allocate(p1["pid"], "memory", 10)

    cycle = rm.detect_cycle()
    finding = {"error_type": "deadlock", "pid": cycle[0], "details": "test", "cycle": cycle}
    action = recover_deadlock(finding, rm)

    assert action["target_pid"] == p2["pid"]  # Low priority process is terminated.
    refreshed = process_manager.get_process(p2["pid"])
    assert refreshed["state"] == "TERMINATED"
