"""Standard scheduling-evaluation metrics, per the research report's
"Benchmarking Procura against real traces" section.

Metrics implemented (all with citations traced back to the research report):
  - makespan: completion time of the last job in the batch.
  - average turnaround time: completion - submission, averaged.
  - average waiting time: start - submission, averaged.
  - utilization: sum(size_j * runtime_j) / (M * makespan)
    (Batsim docs; arXiv 2111.10200). `size_j` here is each job's number of
    "processors" -- Procura's simulated processes don't request a
    processor count, so we treat every job as size 1 (single CPU unit),
    and M (machine/CPU count) is 1 (Procura schedules onto a single
    simulated CPU). This degenerates to busy_time / makespan, which is the
    same quantity `cpu_utilization` in os_sim/scheduler.py already reports
    -- this module recomputes it independently from raw gantt data so the
    benchmark doesn't depend on scheduler internals.
  - Jain's Fairness Index: reused directly from os_sim.scheduler.
  - starvation: NO universal formula exists across the literature (the
    report is explicit about this), so we define our own, as the report
    recommends: max observed wait time, plus the count/rate of processes
    whose wait time exceeds a stated threshold (default 30 "minutes" on
    this sim's timeline, matching the threshold used in the GPU-scheduling
    starvation paper the report cites, arXiv 2512.10980).
"""

from __future__ import annotations

from typing import Any

from os_sim.scheduler import jains_fairness_index

DEFAULT_STARVATION_THRESHOLD = 30.0


def makespan(gantt: list[dict[str, Any]]) -> float:
    if not gantt:
        return 0.0
    return max(s["end"] for s in gantt)


def average_turnaround_time(per_process: list[dict[str, Any]]) -> float:
    if not per_process:
        return 0.0
    return sum(p["turnaround_time"] for p in per_process) / len(per_process)


def average_waiting_time(per_process: list[dict[str, Any]]) -> float:
    if not per_process:
        return 0.0
    return sum(p["waiting_time"] for p in per_process) / len(per_process)


def utilization(gantt: list[dict[str, Any]], num_machines: int = 1) -> float:
    """utilization = sum(size_j * runtime_j) / (M * makespan).

    Every simulated job has size_j = 1 (Procura does not model multi-
    processor job requests), so this reduces to busy_time / (M * makespan).
    """
    span = makespan(gantt)
    if span <= 0 or num_machines <= 0:
        return 0.0
    busy_time = sum(s["end"] - s["start"] for s in gantt)
    return busy_time / (num_machines * span)


def fairness_index(per_process_cpu_times: list[float]) -> float:
    return jains_fairness_index(per_process_cpu_times)


def starvation_metrics(per_process: list[dict[str, Any]], threshold: float = DEFAULT_STARVATION_THRESHOLD) -> dict[str, Any]:
    """Self-defined starvation metric (the report is explicit that no
    universal formula exists): max observed wait time, plus the count and
    rate of processes whose wait time exceeded `threshold`.
    """
    if not per_process:
        return {"max_wait": 0.0, "exceeding_count": 0, "exceeding_rate": 0.0, "threshold": threshold}
    waits = [p["waiting_time"] for p in per_process]
    exceeding = [w for w in waits if w > threshold]
    return {
        "max_wait": max(waits),
        "exceeding_count": len(exceeding),
        "exceeding_rate": len(exceeding) / len(per_process),
        "threshold": threshold,
    }


def summarize(result: dict[str, Any], num_machines: int = 1, starvation_threshold: float = DEFAULT_STARVATION_THRESHOLD) -> dict[str, Any]:
    """Compute the full standard metric set from a single run_schedule() result."""
    gantt = result["gantt"]
    per_process = result["metrics"]["per_process"]
    cpu_time_per_pid: dict[int, float] = {}
    for s in gantt:
        cpu_time_per_pid[s["pid"]] = cpu_time_per_pid.get(s["pid"], 0.0) + (s["end"] - s["start"])

    return {
        "algorithm": result["algorithm"],
        "makespan": round(makespan(gantt), 2),
        "average_turnaround_time": round(average_turnaround_time(per_process), 2),
        "average_waiting_time": round(average_waiting_time(per_process), 2),
        "utilization": round(utilization(gantt, num_machines), 4),
        "fairness_index": round(fairness_index(list(cpu_time_per_pid.values())), 4),
        "starvation": starvation_metrics(per_process, starvation_threshold),
    }
