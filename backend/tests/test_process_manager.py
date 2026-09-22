import pytest

from os_sim import process_manager
from os_sim.states import InvalidTransitionError


def test_create_process_starts_ready():
    proc = process_manager.create_process(name="Test task", burst_time=10)
    assert proc["state"] == "READY"
    assert proc["pid"] > 0


def test_valid_transition_sequence():
    proc = process_manager.create_process(name="Task", burst_time=5)
    pid = proc["pid"]
    running = process_manager.start_process(pid)
    assert running["state"] == "RUNNING"
    blocked = process_manager.pause_process(pid)
    assert blocked["state"] == "BLOCKED"
    ready = process_manager.resume_process(pid)
    assert ready["state"] == "READY"
    running2 = process_manager.start_process(pid)
    assert running2["state"] == "RUNNING"
    done = process_manager.complete_process(pid)
    assert done["state"] == "COMPLETED"


def test_invalid_transition_rejected():
    proc = process_manager.create_process(name="Task", burst_time=5)
    pid = proc["pid"]
    # READY -> COMPLETED is not a legal direct transition.
    with pytest.raises(InvalidTransitionError):
        process_manager.transition_state(pid, "COMPLETED")


def test_completed_is_terminal():
    proc = process_manager.create_process(name="Task", burst_time=5)
    pid = proc["pid"]
    process_manager.start_process(pid)
    process_manager.complete_process(pid)
    with pytest.raises(InvalidTransitionError):
        process_manager.transition_state(pid, "READY")


def test_terminate_from_ready():
    proc = process_manager.create_process(name="Task", burst_time=5)
    pid = proc["pid"]
    terminated = process_manager.terminate_process(pid)
    assert terminated["state"] == "TERMINATED"


def test_increment_error_count():
    proc = process_manager.create_process(name="Task", burst_time=5)
    pid = proc["pid"]
    updated = process_manager.increment_error_count(pid)
    assert updated["error_count"] == 1
    updated2 = process_manager.increment_error_count(pid)
    assert updated2["error_count"] == 2


def test_delete_process():
    proc = process_manager.create_process(name="Task", burst_time=5)
    pid = proc["pid"]
    assert process_manager.delete_process(pid) is True
    assert process_manager.delete_process(pid) is False
