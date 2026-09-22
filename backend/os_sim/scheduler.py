"""CPU scheduling algorithms operating on the READY process list.

All algorithms are non-preemptive except Round Robin. Each returns a dict:
    {
        "algorithm": str,
        "order": [pid, ...],          # dispatch order
        "gantt": [{"pid", "name", "start", "end"}, ...],
        "metrics": {
            "per_process": [{"pid", "name", "completion_time", "turnaround_time",
                              "waiting_time", "response_time"}, ...],
            "average_waiting_time": float,
            "average_turnaround_time": float,
            "average_response_time": float,
            "cpu_utilization": float,   # percent of the makespan the CPU was busy
        },
    }

Time is modelled on a single relative timeline in minutes, anchored at the
earliest arrival_time among the given processes (arrival_time == 0).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Effective-priority sub-scores (each documented, each roughly 0-100 range)
# ---------------------------------------------------------------------------


def user_priority_score(priority: Any) -> float:
    """Map a user-set priority label (or numeric value) to a 0-100 score."""
    if isinstance(priority, str):
        mapping = {"high": 90.0, "medium": 50.0, "low": 20.0}
        return mapping.get(priority.strip().lower(), 50.0)
    try:
        return max(0.0, min(100.0, float(priority)))
    except (TypeError, ValueError):
        return 50.0


def deadline_urgency_score(deadline: Optional[str], now: Optional[datetime] = None) -> float:
    """Score rises as a deadline approaches; 0 if there is no deadline.

    A deadline already passed scores the maximum (100). A deadline more than
    48 hours away scores near 0. Linear falloff in between.
    """
    if not deadline:
        return 0.0
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        dl = datetime.fromisoformat(deadline.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return 0.0
    hours_remaining = (dl - now).total_seconds() / 3600.0
    if hours_remaining <= 0:
        return 100.0
    if hours_remaining >= 48:
        return 0.0
    return 100.0 * (1 - hours_remaining / 48.0)


def waiting_time_score(ready_since: Optional[str], now: Optional[datetime] = None) -> float:
    """Score increases the longer a process has sat in READY (anti-starvation)."""
    if not ready_since:
        return 0.0
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        since = datetime.fromisoformat(ready_since.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return 0.0
    minutes_waited = max(0.0, (now - since).total_seconds() / 60.0)
    # Cap at 100, gaining ~10 points per 5 minutes waited.
    return min(100.0, minutes_waited * 2.0)


def resource_requirement_score(memory_requirement: float, cpu_requirement: float) -> float:
    """Heavier resource demands nudge priority up slightly (they block more
    of the system while waiting, so getting them done frees resources sooner).
    """
    mem_component = min(60.0, (memory_requirement or 0) / 2048.0 * 60.0)
    cpu_component = min(40.0, (cpu_requirement or 0) / 100.0 * 40.0)
    return mem_component + cpu_component


def effective_priority_score(proc: dict[str, Any], now: Optional[datetime] = None) -> float:
    return (
        user_priority_score(proc.get("priority"))
        + deadline_urgency_score(proc.get("deadline"), now)
        + waiting_time_score(proc.get("ready_since"), now)
        + resource_requirement_score(proc.get("memory_requirement", 0), proc.get("cpu_requirement", 0))
    )


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _parse_arrival(value: Any) -> float:
    """Accept either an ISO datetime string or a bare number (minutes)."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _relative_arrivals(processes: list[dict[str, Any]]) -> dict[int, float]:
    raw = {p["pid"]: _parse_arrival(p.get("arrival_time")) for p in processes}
    if not raw:
        return {}
    base = min(raw.values())
    # Convert to minutes relative to the earliest arrival.
    return {pid: round((t - base) / 60.0, 2) if t > 1e6 else round(t - base, 2) for pid, t in raw.items()}


# ---------------------------------------------------------------------------
# Metrics computation shared by non-preemptive algorithms
# ---------------------------------------------------------------------------


def _build_metrics(
    processes_by_pid: dict[int, dict[str, Any]],
    gantt: list[dict[str, Any]],
    arrivals: dict[int, float],
) -> dict[str, Any]:
    first_start: dict[int, float] = {}
    last_end: dict[int, float] = {}
    for slice_ in gantt:
        pid = slice_["pid"]
        first_start.setdefault(pid, slice_["start"])
        last_end[pid] = slice_["end"]

    per_process = []
    total_wait = total_turnaround = total_response = 0.0
    n = len(processes_by_pid)
    for pid, proc in processes_by_pid.items():
        arrival = arrivals.get(pid, 0.0)
        burst = proc.get("burst_time", 0)
        completion = last_end.get(pid, arrival + burst)
        turnaround = completion - arrival
        waiting = turnaround - burst
        response = first_start.get(pid, arrival) - arrival
        per_process.append(
            {
                "pid": pid,
                "name": proc.get("name"),
                "completion_time": round(completion, 2),
                "turnaround_time": round(turnaround, 2),
                "waiting_time": round(waiting, 2),
                "response_time": round(response, 2),
            }
        )
        total_wait += waiting
        total_turnaround += turnaround
        total_response += response

    makespan = max((s["end"] for s in gantt), default=0)
    busy_time = sum(s["end"] - s["start"] for s in gantt)
    cpu_utilization = round((busy_time / makespan * 100.0), 2) if makespan > 0 else 0.0

    return {
        "per_process": per_process,
        "average_waiting_time": round(total_wait / n, 2) if n else 0.0,
        "average_turnaround_time": round(total_turnaround / n, 2) if n else 0.0,
        "average_response_time": round(total_response / n, 2) if n else 0.0,
        "cpu_utilization": cpu_utilization,
    }


def _run_nonpreemptive(processes: list[dict[str, Any]], order: list[dict[str, Any]], algorithm: str) -> dict[str, Any]:
    arrivals = _relative_arrivals(processes)
    by_pid = {p["pid"]: p for p in processes}

    clock = 0.0
    gantt = []
    for proc in order:
        pid = proc["pid"]
        arrival = arrivals.get(pid, 0.0)
        start = max(clock, arrival)
        end = start + proc.get("burst_time", 0)
        gantt.append({"pid": pid, "name": proc.get("name"), "start": round(start, 2), "end": round(end, 2)})
        clock = end

    metrics = _build_metrics(by_pid, gantt, arrivals)
    return {
        "algorithm": algorithm,
        "order": [p["pid"] for p in order],
        "gantt": gantt,
        "metrics": metrics,
    }


def fcfs(processes: list[dict[str, Any]]) -> dict[str, Any]:
    """First-Come First-Served: dispatch strictly in arrival order."""
    arrivals = _relative_arrivals(processes)
    order = sorted(processes, key=lambda p: (arrivals.get(p["pid"], 0.0), p["pid"]))
    return _run_nonpreemptive(processes, order, "fcfs")


def sjf(processes: list[dict[str, Any]]) -> dict[str, Any]:
    """Shortest Job First (non-preemptive): dispatch by ascending burst time."""
    order = sorted(processes, key=lambda p: (p.get("burst_time", 0), p["pid"]))
    return _run_nonpreemptive(processes, order, "sjf")


def priority_scheduling(processes: list[dict[str, Any]], now: Optional[datetime] = None) -> dict[str, Any]:
    """Priority scheduling by descending effective_priority_score."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    order = sorted(processes, key=lambda p: (-effective_priority_score(p, now), p["pid"]))
    result = _run_nonpreemptive(processes, order, "priority")
    scores = {p["pid"]: round(effective_priority_score(p, now), 2) for p in processes}
    for pp in result["metrics"]["per_process"]:
        pp["effective_priority_score"] = scores.get(pp["pid"])
    return result


def round_robin(processes: list[dict[str, Any]], quantum: int = 4) -> dict[str, Any]:
    """Round Robin with a fixed time quantum, cycling through the ready queue.

    Standard simulation: processes are admitted to the ready queue in arrival
    order; each dispatch runs for at most `quantum` time units, and any
    process that arrives during a slice is admitted before the just-run
    process is re-queued (if it still has remaining burst time).
    """
    arrivals = _relative_arrivals(processes)
    by_pid = {p["pid"]: p for p in processes}
    order_seq = sorted(processes, key=lambda p: (arrivals.get(p["pid"], 0.0), p["pid"]))

    remaining = {p["pid"]: p.get("burst_time", 0) for p in order_seq}
    n = len(order_seq)
    i = 0  # pointer into order_seq for not-yet-admitted processes
    queue: list[int] = []
    clock = 0.0
    gantt: list[dict[str, Any]] = []
    dispatch_order: list[int] = []

    # Admit every process that has arrived by time `clock`.
    def admit(up_to: float) -> None:
        nonlocal i
        while i < n and arrivals.get(order_seq[i]["pid"], 0.0) <= up_to:
            queue.append(order_seq[i]["pid"])
            i += 1

    admit(clock)

    while queue or i < n:
        if not queue:
            # Fast-forward the clock to the next arrival.
            clock = arrivals.get(order_seq[i]["pid"], clock)
            admit(clock)
            continue

        pid = queue.pop(0)
        if remaining[pid] <= 0:
            continue
        proc = by_pid[pid]
        run_time = min(quantum, remaining[pid])
        start = clock
        end = start + run_time
        gantt.append({"pid": pid, "name": proc.get("name"), "start": round(start, 2), "end": round(end, 2)})
        dispatch_order.append(pid)
        remaining[pid] -= run_time
        clock = end

        admit(clock)
        if remaining[pid] > 0:
            queue.append(pid)

    metrics = _build_metrics(by_pid, gantt, arrivals)
    return {
        "algorithm": "round_robin",
        "quantum": quantum,
        "order": dispatch_order,
        "gantt": gantt,
        "metrics": metrics,
    }


ALGORITHMS = {
    "fcfs": fcfs,
    "sjf": sjf,
    "priority": priority_scheduling,
    "round_robin": round_robin,
}


def run_schedule(algorithm: str, processes: list[dict[str, Any]], quantum: int = 4) -> dict[str, Any]:
    algorithm = algorithm.lower()
    if algorithm not in ALGORITHMS:
        raise ValueError(f"Unknown algorithm: {algorithm}. Choose from {sorted(ALGORITHMS)}")
    if algorithm == "round_robin":
        return round_robin(processes, quantum=quantum)
    return ALGORITHMS[algorithm](processes)
