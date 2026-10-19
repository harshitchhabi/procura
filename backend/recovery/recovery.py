"""Rule-based recovery scripts, one per failure type.

    memory_failure -> suspend the lowest-effective-priority process holding
                       memory, free it, retry the failed allocation.
    timeout        -> stop (block) the offending process, log it, retry
                       (return it to READY).
    crash          -> save the error, restart the process (READY), bump its
                       retry/error count.
    deadlock       -> terminate the lowest-priority process in the detected
                       cycle, release its resources, resume the others.

Every action returns a small dict describing what was done; main.py is
responsible for persisting it via database.log_recovery_action.
"""

from __future__ import annotations

from typing import Any, Optional

from os_sim import process_manager
from os_sim.resource_manager import ResourceManager
from os_sim.scheduler import effective_priority_score


def _lowest_priority_pid(pids: list[int], exclude: Optional[int] = None) -> Optional[int]:
    candidates = []
    for pid in pids:
        if pid == exclude:
            continue
        try:
            proc = process_manager.get_process(pid)
        except Exception:
            continue
        candidates.append((effective_priority_score(proc), pid))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    return candidates[0][1]


def recover_memory_failure(finding: dict[str, Any], resource_mgr: ResourceManager) -> dict[str, Any]:
    failing_pid = finding["pid"]
    try:
        process_manager.increment_error_count(failing_pid)
    except Exception:
        pass

    # Findings are snapshotted before any recovery runs, so an earlier recovery
    # in the same pass may already have freed enough memory: retry first.
    try:
        failing = process_manager.get_process(failing_pid)
        needed = failing.get("memory_requirement", 0) - resource_mgr.holders["memory"].get(failing_pid, 0)
        if needed <= resource_mgr.available("memory"):
            result = resource_mgr.allocate(failing_pid, "memory", needed)
            if result.get("success"):
                return {
                    "action_type": "retry",
                    "target_pid": failing_pid,
                    "message": f"Memory had become available since detection; retried allocation: {result['message']}",
                }
    except Exception:
        pass

    holders = list(resource_mgr.holders.get("memory", {}).keys())
    victim = _lowest_priority_pid(holders, exclude=failing_pid)

    # Like Kubernetes' DefaultPreemption: only evict a strictly lower-priority
    # holder (otherwise two processes can evict each other forever), and only
    # if evicting it actually frees enough memory for the failing process.
    if victim is not None:
        try:
            failing = process_manager.get_process(failing_pid)
            if effective_priority_score(process_manager.get_process(victim)) >= effective_priority_score(failing):
                victim = None
            else:
                needed = failing.get("memory_requirement", 0) - resource_mgr.holders["memory"].get(failing_pid, 0)
                freed = resource_mgr.holders["memory"].get(victim, 0)
                if resource_mgr.available("memory") + freed < needed:
                    victim = None
        except Exception:
            victim = None

    if victim is None:
        return {
            "action_type": "memory_failure_no_victim",
            "target_pid": failing_pid,
            "message": (
                "No lower-priority process holds enough memory to make this allocation fit; "
                "failing process left pending."
            ),
        }

    resource_mgr.release(victim, "memory")
    try:
        proc = process_manager.get_process(victim)
        if proc["state"] == "RUNNING":
            process_manager.transition_state(victim, "BLOCKED")
    except Exception:
        pass

    try:
        proc = process_manager.get_process(failing_pid)
        retry_result = resource_mgr.allocate(failing_pid, "memory", proc.get("memory_requirement", 0))
    except Exception:
        retry_result = {"success": False, "message": "Failing process no longer exists."}

    return {
        "action_type": "suspend_and_retry",
        "target_pid": victim,
        "message": (
            f"Suspended pid {victim} to free memory. Retried allocation for pid {failing_pid}: "
            f"{retry_result['message']}"
        ),
    }


def recover_timeout(finding: dict[str, Any]) -> dict[str, Any]:
    pid = finding["pid"]
    try:
        proc = process_manager.get_process(pid)
        if proc["state"] == "RUNNING":
            process_manager.transition_state(pid, "BLOCKED")
        process_manager.transition_state(pid, "READY")
        process_manager.increment_error_count(pid)
        message = f"Stopped pid {pid} (timeout), logged, and requeued it in READY for retry."
    except Exception as exc:
        message = f"Could not requeue pid {pid}: {exc}"
    return {"action_type": "stop_and_retry", "target_pid": pid, "message": message}


def recover_crash(finding: dict[str, Any]) -> dict[str, Any]:
    pid = finding["pid"]
    try:
        proc = process_manager.get_process(pid)
        if proc["state"] == "RUNNING":
            process_manager.transition_state(pid, "BLOCKED")
        process_manager.transition_state(pid, "READY")
        process_manager.increment_error_count(pid)
        message = f"Restarted pid {pid} after crash; error_count incremented."
    except Exception as exc:
        message = f"Could not restart pid {pid}: {exc}"
    return {"action_type": "restart", "target_pid": pid, "message": message}


def recover_deadlock(finding: dict[str, Any], resource_mgr: ResourceManager) -> dict[str, Any]:
    cycle = finding.get("cycle", [])
    if not cycle:
        return {"action_type": "deadlock_no_cycle", "target_pid": None, "message": "No cycle data available."}

    victim = _lowest_priority_pid(cycle)
    resource_mgr.release_all_for_pid(victim)
    try:
        proc = process_manager.get_process(victim)
        if proc["state"] in ("READY", "RUNNING", "BLOCKED"):
            process_manager.transition_state(victim, "TERMINATED")
    except Exception:
        pass

    resumed = []
    for pid in cycle:
        if pid == victim:
            continue
        try:
            proc = process_manager.get_process(pid)
            if proc["state"] == "BLOCKED":
                process_manager.transition_state(pid, "READY")
                resumed.append(pid)
        except Exception:
            continue

    return {
        "action_type": "terminate_and_resume",
        "target_pid": victim,
        "message": (
            f"Terminated pid {victim} (lowest priority in cycle {cycle}) and released its resources. "
            f"Resumed: {resumed or 'none'}."
        ),
    }


RECOVERY_HANDLERS = {
    "memory_failure": recover_memory_failure,
    "timeout": recover_timeout,
    "burst_anomaly": recover_timeout,
    "crash": recover_crash,
    "deadlock": recover_deadlock,
}


def run_recovery(finding: dict[str, Any], resource_mgr: ResourceManager) -> dict[str, Any]:
    error_type = finding.get("error_type")
    handler = RECOVERY_HANDLERS.get(error_type)
    if handler is None:
        return {"action_type": "no_action", "target_pid": finding.get("pid"), "message": f"No recovery script for {error_type}."}
    if error_type in ("memory_failure",):
        return handler(finding, resource_mgr)
    if error_type == "deadlock":
        return handler(finding, resource_mgr)
    return handler(finding)
