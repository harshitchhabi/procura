"""Error detection: burst-time anomalies, memory allocation failures, deadlocks."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from os_sim.resource_manager import ResourceManager

ANOMALY_MULTIPLIER = 1.5
HIGH_CPU_THRESHOLD = 80.0  # percent of CPU pool considered "high usage"


def detect_burst_anomaly(process: dict[str, Any], actual_running_minutes: float, resource_mgr: ResourceManager) -> Optional[dict[str, Any]]:
    """Flag a process as anomalous if it has run far longer than its declared
    burst_time while system CPU usage is high (i.e. it's hogging the CPU
    rather than legitimately taking longer)."""
    burst = process.get("burst_time", 0)
    if burst <= 0:
        return None
    cpu_util = resource_mgr.utilization()["cpu"]["utilization_pct"]
    if actual_running_minutes > burst * ANOMALY_MULTIPLIER and cpu_util >= HIGH_CPU_THRESHOLD:
        return {
            "error_type": "burst_anomaly",
            "pid": process["pid"],
            "details": (
                f"pid {process['pid']} ({process.get('name')}) has run {actual_running_minutes:.1f} min, "
                f"exceeding 1.5x its declared burst_time of {burst} min, while CPU utilization is {cpu_util}%."
            ),
        }
    return None


def detect_memory_failure(process: dict[str, Any], resource_mgr: ResourceManager) -> Optional[dict[str, Any]]:
    """Flag a memory_failure if a process's declared memory_requirement
    exceeds what's currently available in the memory pool."""
    requirement = process.get("memory_requirement", 0)
    available = resource_mgr.available("memory")
    if requirement > available:
        return {
            "error_type": "memory_failure",
            "pid": process["pid"],
            "details": (
                f"pid {process['pid']} ({process.get('name')}) requires {requirement}MB memory "
                f"but only {available}MB is available."
            ),
        }
    return None


def detect_deadlock(resource_mgr: ResourceManager) -> Optional[dict[str, Any]]:
    """Flag a deadlock if the waits-for graph contains a cycle."""
    cycle = resource_mgr.detect_cycle()
    if cycle:
        return {
            "error_type": "deadlock",
            "pid": cycle[0],
            "details": f"Circular wait detected among pids: {' -> '.join(str(p) for p in cycle)}.",
            "cycle": cycle,
        }
    return None


def run_detection(processes: list[dict[str, Any]], resource_mgr: ResourceManager) -> list[dict[str, Any]]:
    """Run all detectors across the given processes and resource manager state."""
    findings: list[dict[str, Any]] = []

    deadlock = detect_deadlock(resource_mgr)
    if deadlock:
        findings.append(deadlock)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for proc in processes:
        mem_issue = detect_memory_failure(proc, resource_mgr)
        if mem_issue:
            findings.append(mem_issue)

        if proc.get("state") == "RUNNING" and proc.get("started_at"):
            try:
                started = datetime.fromisoformat(str(proc["started_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
                running_minutes = (now - started).total_seconds() / 60.0
            except ValueError:
                running_minutes = 0.0
            anomaly = detect_burst_anomaly(proc, running_minutes, resource_mgr)
            if anomaly:
                findings.append(anomaly)

    return findings
