"""Process lifecycle management: CRUD + state transitions on top of database.py."""

from __future__ import annotations

from typing import Any, Optional

import database
from os_sim.states import State, validate_transition


class ProcessNotFoundError(Exception):
    pass


def create_process(
    name: str,
    description: str = "",
    priority: str = "Medium",
    deadline: Optional[str] = None,
    burst_time: int = 10,
    memory_requirement: int = 0,
    cpu_requirement: int = 0,
    arrival_time: Optional[str] = None,
) -> dict[str, Any]:
    proc = database.create_process(
        name=name,
        description=description,
        priority=priority,
        deadline=deadline,
        burst_time=burst_time,
        memory_requirement=memory_requirement,
        cpu_requirement=cpu_requirement,
        arrival_time=arrival_time,
    )
    # NEW -> READY immediately: task has been admitted to the ready queue.
    return transition_state(proc["pid"], State.READY)


def get_process(pid: int) -> dict[str, Any]:
    proc = database.get_process(pid)
    if proc is None:
        raise ProcessNotFoundError(f"No process with pid {pid}")
    return proc


def list_processes(state: Optional[str] = None) -> list[dict[str, Any]]:
    return database.list_processes(state=state)


def transition_state(pid: int, target: str) -> dict[str, Any]:
    proc = get_process(pid)
    validate_transition(proc["state"], target)
    fields: dict[str, Any] = {"state": target}
    if target == State.RUNNING and proc.get("started_at") is None:
        fields["started_at"] = database.now_iso()
    if target == State.READY:
        fields["ready_since"] = database.now_iso()
    updated = database.update_process(pid, **fields)
    assert updated is not None
    return updated


def start_process(pid: int) -> dict[str, Any]:
    return transition_state(pid, State.RUNNING)


def pause_process(pid: int) -> dict[str, Any]:
    """Move a RUNNING process to BLOCKED (paused / waiting on a resource)."""
    return transition_state(pid, State.BLOCKED)


def resume_process(pid: int) -> dict[str, Any]:
    """Move a BLOCKED process back to READY."""
    return transition_state(pid, State.READY)


def complete_process(pid: int) -> dict[str, Any]:
    return transition_state(pid, State.COMPLETED)


def terminate_process(pid: int) -> dict[str, Any]:
    return transition_state(pid, State.TERMINATED)


def increment_error_count(pid: int) -> dict[str, Any]:
    proc = get_process(pid)
    updated = database.update_process(pid, error_count=proc["error_count"] + 1)
    assert updated is not None
    return updated


def delete_process(pid: int) -> bool:
    return database.delete_process(pid)
