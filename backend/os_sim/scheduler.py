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

import heapq
import math
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


def _decay_factor(last_update_minutes_ago: float, half_life_minutes: float) -> float:
    """Exponential decay factor, analogous to Slurm's PriorityDecayHalfLife.

    Slurm's fair-share factor decays accumulated historical usage over time
    via a configurable half-life so that old usage matters less than recent
    usage (research report, "Kubernetes, Slurm, and Celery" section, citing
    the Bayreuth/Fastone Slurm fair-share docs). `decay = 0.5 ** (age / half_life)`.
    """
    if half_life_minutes <= 0:
        return 1.0
    return 0.5 ** (max(0.0, last_update_minutes_ago) / half_life_minutes)


def fair_share_score(
    proc: dict[str, Any],
    all_processes: Optional[list[dict[str, Any]]] = None,
    now: Optional[datetime] = None,
    half_life_minutes: float = 60.0,
) -> float:
    """Slurm-style fair-share penalty, additive to effective_priority_score.

    Per the research report ("Kubernetes, Slurm, and Celery" section): Slurm
    computes a composite priority as a weighted sum of normalized [0,1]
    factors (age, fair-share, job size, QOS, partition), where the
    fair-share factor specifically *lowers* priority for
    accounts/processes that have already consumed more than their
    proportional share of historical CPU time, with that historical usage
    decaying exponentially via a configurable half-life
    (`PriorityDecayHalfLife`).

    Procura simplification (no account/group model exists, so this is
    applied per-process): each process carries an optional
    `cumulative_cpu_time` (simulated minutes of CPU already consumed) and
    `cumulative_cpu_time_at` (ISO timestamp of that measurement). We decay
    every process's consumed time to "now", compare each process's decayed
    consumption against an equal (1/n) fair share of the total decayed
    consumption across all given processes, and return a penalty
    (negative contribution, 0..-100) proportional to how far over its fair
    share a process is. Processes with no recorded usage (the common case
    for brand-new tasks) get a score of exactly 0 -- this keeps the term
    purely additive and backward compatible with existing effective-priority
    callers/tests that don't track cumulative usage.
    """
    all_processes = all_processes or [proc]
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)

    def decayed_usage(p: dict[str, Any]) -> float:
        consumed = p.get("cumulative_cpu_time", 0.0) or 0.0
        if consumed <= 0:
            return 0.0
        last_at = p.get("cumulative_cpu_time_at")
        age_minutes = 0.0
        if last_at:
            try:
                last_dt = datetime.fromisoformat(str(last_at).replace("Z", "+00:00")).replace(tzinfo=None)
                age_minutes = max(0.0, (now - last_dt).total_seconds() / 60.0)
            except ValueError:
                age_minutes = 0.0
        return consumed * _decay_factor(age_minutes, half_life_minutes)

    my_usage = decayed_usage(proc)
    if my_usage <= 0:
        return 0.0

    total_usage = sum(decayed_usage(p) for p in all_processes)
    n = len(all_processes)
    if total_usage <= 0 or n == 0:
        return 0.0

    fair_share = total_usage / n
    excess = my_usage - fair_share
    if excess <= 0:
        return 0.0
    # Scale the excess (relative to total usage) into a 0-100 penalty band.
    penalty = min(100.0, (excess / total_usage) * 100.0 * n)
    return -penalty


def effective_priority_score(
    proc: dict[str, Any],
    now: Optional[datetime] = None,
    all_processes: Optional[list[dict[str, Any]]] = None,
) -> float:
    return (
        user_priority_score(proc.get("priority"))
        + deadline_urgency_score(proc.get("deadline"), now)
        + waiting_time_score(proc.get("ready_since"), now)
        + resource_requirement_score(proc.get("memory_requirement", 0), proc.get("cpu_requirement", 0))
        + fair_share_score(proc, all_processes, now)
    )


# ---------------------------------------------------------------------------
# Jain's Fairness Index (research report, "Fairness and starvation" section;
# originates from Jain/Chiu/Hawe 1984 DEC technical report, arXiv cs/9809099)
# ---------------------------------------------------------------------------


def jains_fairness_index(values: list[float]) -> float:
    """f(x) = (sum(x))^2 / (n * sum(x_i^2)).

    Range is [1/n, 1]: 1.0 means every value is identical (perfectly fair
    allocation), 1/n means one entity received everything (maximally
    unfair). If all values are zero (e.g. nothing ever ran), we treat the
    allocation as trivially fair and return 1.0.
    """
    n = len(values)
    if n == 0:
        return 0.0
    total = sum(values)
    sum_sq = sum(v * v for v in values)
    if sum_sq == 0:
        return 1.0
    return (total * total) / (n * sum_sq)


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


SLOWDOWN_BOUND = 1.0  # minutes; keeps very short jobs from dominating (Feitelson's "bounded slowdown")


def bounded_slowdown(turnaround: float, burst: float, bound: float = SLOWDOWN_BOUND) -> float:
    """max(turnaround / max(burst, bound), 1). 1.0 means the job was never delayed."""
    return max(turnaround / max(burst, bound), 1.0)


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
    slowdowns: list[float] = []
    total_wait = total_turnaround = total_response = 0.0
    n = len(processes_by_pid)
    for pid, proc in processes_by_pid.items():
        arrival = arrivals.get(pid, 0.0)
        burst = proc.get("burst_time", 0)
        completion = last_end.get(pid, arrival + burst)
        turnaround = completion - arrival
        waiting = turnaround - burst
        response = first_start.get(pid, arrival) - arrival
        slowdown = bounded_slowdown(turnaround, burst)
        per_process.append(
            {
                "pid": pid,
                "name": proc.get("name"),
                "completion_time": round(completion, 2),
                "turnaround_time": round(turnaround, 2),
                "waiting_time": round(waiting, 2),
                "response_time": round(response, 2),
                "bounded_slowdown": round(slowdown, 3),
            }
        )
        slowdowns.append(slowdown)
        total_wait += waiting
        total_turnaround += turnaround
        total_response += response

    makespan = max((s["end"] for s in gantt), default=0)
    busy_time = sum(s["end"] - s["start"] for s in gantt)
    cpu_utilization = round((busy_time / makespan * 100.0), 2) if makespan > 0 else 0.0

    # Jain's Fairness Index over each process's cumulative allocated CPU
    # time this run (research report, "Fairness and starvation" section).
    # Applied uniformly across every algorithm so all six are comparable.
    cpu_time_per_pid: dict[int, float] = {pid: 0.0 for pid in processes_by_pid}
    for slice_ in gantt:
        cpu_time_per_pid[slice_["pid"]] = cpu_time_per_pid.get(slice_["pid"], 0.0) + (slice_["end"] - slice_["start"])
    fairness_index = round(jains_fairness_index(list(cpu_time_per_pid.values())), 4)

    # Fairness over *delay*, not over total service. Every algorithm here runs
    # each process to completion, so the index above is the same for all of
    # them. Jain's index over each process's normalised service rate
    # (1 / bounded slowdown) separates them: it is 1.0 only when every
    # process is slowed down by the same factor.
    service_rates = [1.0 / s for s in slowdowns]
    waiting_fairness = round(jains_fairness_index(service_rates), 4) if service_rates else 0.0

    return {
        "per_process": per_process,
        "average_waiting_time": round(total_wait / n, 2) if n else 0.0,
        "average_turnaround_time": round(total_turnaround / n, 2) if n else 0.0,
        "average_response_time": round(total_response / n, 2) if n else 0.0,
        "average_bounded_slowdown": round(sum(slowdowns) / n, 3) if n else 0.0,
        "max_bounded_slowdown": round(max(slowdowns), 3) if slowdowns else 0.0,
        "cpu_utilization": cpu_utilization,
        "fairness_index": fairness_index,
        "delay_fairness_index": waiting_fairness,
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


def _arrival_aware_order(processes: list[dict[str, Any]], key) -> list[dict[str, Any]]:
    """Non-preemptive dispatch order: at each decision point pick the best job
    (lowest `key`) among those that have already arrived; the CPU only idles
    when nothing has arrived yet. Pre-sorting the whole list instead would
    idle the CPU waiting for a late-arriving job while others are ready."""
    arrivals = _relative_arrivals(processes)
    pending = sorted(processes, key=lambda p: (arrivals.get(p["pid"], 0.0), p["pid"]))
    order: list[dict[str, Any]] = []
    clock = 0.0
    while pending:
        ready = [p for p in pending if arrivals.get(p["pid"], 0.0) <= clock]
        if not ready:
            clock = arrivals.get(pending[0]["pid"], 0.0)
            continue
        nxt = min(ready, key=key)
        order.append(nxt)
        pending.remove(nxt)
        clock = max(clock, arrivals.get(nxt["pid"], 0.0)) + nxt.get("burst_time", 0)
    return order


def sjf(processes: list[dict[str, Any]]) -> dict[str, Any]:
    """Shortest Job First (non-preemptive): among arrived jobs, dispatch the shortest burst."""
    arrivals = _relative_arrivals(processes)
    order = _arrival_aware_order(
        processes, key=lambda p: (p.get("burst_time", 0), arrivals.get(p["pid"], 0.0), p["pid"])
    )
    return _run_nonpreemptive(processes, order, "sjf")


def priority_scheduling(processes: list[dict[str, Any]], now: Optional[datetime] = None) -> dict[str, Any]:
    """Priority scheduling by descending effective_priority_score."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    arrivals = _relative_arrivals(processes)
    scores = {p["pid"]: effective_priority_score(p, now, processes) for p in processes}
    order = _arrival_aware_order(
        processes, key=lambda p: (-scores[p["pid"]], arrivals.get(p["pid"], 0.0), p["pid"])
    )
    result = _run_nonpreemptive(processes, order, "priority")
    scores = {pid: round(s, 2) for pid, s in scores.items()}
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


# ---------------------------------------------------------------------------
# EEVDF (Earliest Eligible Virtual Deadline First) -- Linux's scheduler since
# kernel 6.6 (2023/2024), replacing CFS. Research report, "CFS and EEVDF"
# section, citing docs.kernel.org/scheduler/sched-eevdf.html and
# LWN Article 925371. EEVDF is "the stronger and more current citation...
# since it is what Linux actually runs today."
#
# Nice-to-weight mapping: Weight ~= 1024 / 1.25^nice (CS162 Berkeley lecture
# 13), nice 0 -> weight 1024 (WEIGHT_0 below). We derive `nice` from the
# existing priority label so the new algorithm plugs into the same process
# schema as everything else.
# ---------------------------------------------------------------------------

WEIGHT_0 = 1024.0  # nice-0 weight, matches the kernel's sched_prio_to_weight[20]
_PRIORITY_TO_NICE = {"high": -5, "medium": 0, "low": 5}
SCHED_LATENCY = 24.0  # minutes; analog of sched_latency_ns (~24ms) scaled to this sim's minute timeline
MIN_SLICE = 3.0  # minutes; analog of sched_min_granularity_ns (~3ms floor)


def nice_from_priority(priority: Any) -> int:
    """Map Procura's priority label/score to a kernel-style nice value."""
    if isinstance(priority, str):
        return _PRIORITY_TO_NICE.get(priority.strip().lower(), 0)
    try:
        score = max(0.0, min(100.0, float(priority)))
    except (TypeError, ValueError):
        return 0
    # Higher score -> lower (more favorable) nice. Linear map 0..100 -> +10..-10.
    return round(10 - (score / 100.0) * 20.0)


def weight_from_priority(priority: Any) -> float:
    """Weight ~= 1024 / 1.25^nice (CS162 Berkeley lecture 13, via the
    research report's EEVDF section). The real kernel uses a hand-tuned
    lookup table that only approximates this ratio; we use the closed-form
    approximation directly since it's documented as equivalent in spirit."""
    nice = nice_from_priority(priority)
    return WEIGHT_0 / (1.25 ** nice)


def eevdf(processes: list[dict[str, Any]], base_slice: float = MIN_SLICE * 2) -> dict[str, Any]:
    """Earliest Eligible Virtual Deadline First, simulated.

    Each task has a weight derived from its priority. vruntime advances at a
    rate inversely proportional to weight (heavier/higher-priority tasks'
    vruntime grows more slowly per unit of real time, so they're eligible
    more often and get a larger effective CPU share -- the same mechanism as
    CFS, per the research report). A task is *eligible* once its vruntime is
    at or below the weighted-average vruntime of the active set (i.e. its lag
    = avg - vruntime, weighted, is >= 0). Among eligible tasks, the one with
    the earliest *virtual deadline* (vruntime + requested_slice/weight term)
    is dispatched next. A min-heap (heapq) picks the smallest deadline
    efficiently, analogous to the kernel's red-black tree walk to the
    leftmost node.
    """
    arrivals = _relative_arrivals(processes)
    by_pid = {p["pid"]: p for p in processes}
    weights = {p["pid"]: weight_from_priority(p.get("priority")) for p in processes}
    remaining = {p["pid"]: float(p.get("burst_time", 0)) for p in processes}
    vruntime = {p["pid"]: 0.0 for p in processes}

    order_seq = sorted(processes, key=lambda p: (arrivals.get(p["pid"], 0.0), p["pid"]))
    n = len(order_seq)
    i = 0
    active: list[int] = []  # pids currently arrived & unfinished
    clock = 0.0
    gantt: list[dict[str, Any]] = []
    dispatch_order: list[int] = []

    def admit(up_to: float) -> None:
        nonlocal i
        while i < n and arrivals.get(order_seq[i]["pid"], 0.0) <= up_to:
            active.append(order_seq[i]["pid"])
            i += 1

    admit(clock)

    while active or i < n:
        if not active:
            clock = arrivals.get(order_seq[i]["pid"], clock)
            admit(clock)
            continue

        # Weighted-average vruntime of the active set defines eligibility.
        total_w = sum(weights[pid] for pid in active)
        avg_vr = sum(vruntime[pid] * weights[pid] for pid in active) / total_w if total_w else 0.0

        eligible = [pid for pid in active if (avg_vr - vruntime[pid]) >= 0]
        if not eligible:
            # Shouldn't normally happen (avg is a weighted mean), but guard anyway.
            eligible = list(active)

        heap: list[tuple[float, int]] = []
        for pid in eligible:
            deadline = vruntime[pid] + (base_slice * WEIGHT_0 / weights[pid])
            heapq.heappush(heap, (deadline, pid))
        _, pid = heapq.heappop(heap)

        proc = by_pid[pid]
        slice_len = base_slice * WEIGHT_0 / weights[pid]
        # Convert the vruntime-scale slice back to a real-time run length,
        # bounded by remaining burst and a minimum granularity floor.
        real_slice = max(MIN_SLICE, slice_len * weights[pid] / WEIGHT_0)
        run_time = min(real_slice, remaining[pid])

        start = clock
        end = start + run_time
        gantt.append({"pid": pid, "name": proc.get("name"), "start": round(start, 2), "end": round(end, 2)})
        dispatch_order.append(pid)
        remaining[pid] -= run_time
        vruntime[pid] += run_time * WEIGHT_0 / weights[pid]
        clock = end

        admit(clock)
        if remaining[pid] <= 1e-9:
            active.remove(pid)

    metrics = _build_metrics(by_pid, gantt, arrivals)
    return {
        "algorithm": "eevdf",
        "order": dispatch_order,
        "gantt": gantt,
        "metrics": metrics,
    }


# ---------------------------------------------------------------------------
# MLFQ (Multi-Level Feedback Queue) -- OSTEP Ch. 8's five canonical rules
# (research report, "CFS and EEVDF" section, citing
# fog.misty.com/perry/os/Chapters/08-cpu-sched-mlfq/all-notes.html):
#   1. If priority(A) > priority(B), A runs.
#   2. If priority(A) == priority(B), round-robin among them.
#   3. A new job enters at the topmost queue.
#   4. Once a job uses up its time allotment at a level (tracked
#      cumulatively, NOT reset on a voluntary yield -- the "better
#      accounting" anti-gaming rule), it is demoted one level.
#   5. After a boost interval S, every job is moved back to the topmost
#      queue (priority boost), preventing starvation.
# ---------------------------------------------------------------------------


def mlfq(
    processes: list[dict[str, Any]],
    num_queues: int = 3,
    base_quantum: float = 4.0,
    boost_interval: float = 50.0,
) -> dict[str, Any]:
    """Simulated MLFQ with configurable queue count, per-level quantum, and
    boost interval S. Level 0 is the topmost (highest) priority; quantum
    doubles per level (4, 8, 16, ...); allotment == quantum at each level
    (a job gets exactly one quantum's worth of cumulative time per level
    before demotion, matching OSTEP's simplest allotment model).
    """
    arrivals = _relative_arrivals(processes)
    by_pid = {p["pid"]: p for p in processes}
    remaining = {p["pid"]: float(p.get("burst_time", 0)) for p in processes}

    quantum_at_level = [base_quantum * (2 ** level) for level in range(num_queues)]
    level: dict[int, int] = {}
    # Cumulative time used *at the current level* since the last demotion or
    # boost -- NOT reset by a voluntary yield (e.g. being preempted by an
    # arrival), which is exactly the gaming exploit rule 4 exists to close.
    used_at_level: dict[int, float] = {}

    order_seq = sorted(processes, key=lambda p: (arrivals.get(p["pid"], 0.0), p["pid"]))
    n = len(order_seq)
    i = 0
    queues: list[list[int]] = [[] for _ in range(num_queues)]
    clock = 0.0
    last_boost = 0.0
    gantt: list[dict[str, Any]] = []
    dispatch_order: list[int] = []

    def admit(up_to: float) -> None:
        nonlocal i
        while i < n and arrivals.get(order_seq[i]["pid"], 0.0) <= up_to:
            pid = order_seq[i]["pid"]
            level[pid] = 0  # rule 3: new jobs enter at the topmost queue
            used_at_level[pid] = 0.0
            queues[0].append(pid)
            i += 1

    def maybe_boost(up_to: float) -> None:
        nonlocal last_boost
        while up_to - last_boost >= boost_interval:
            last_boost += boost_interval
            for lvl in range(1, num_queues):
                while queues[lvl]:
                    pid = queues[lvl].pop(0)
                    level[pid] = 0
                    used_at_level[pid] = 0.0
                    queues[0].append(pid)

    admit(clock)

    while any(queues) or i < n:
        maybe_boost(clock)
        active_queue = next((lvl for lvl in range(num_queues) if queues[lvl]), None)
        if active_queue is None:
            if i < n:
                clock = arrivals.get(order_seq[i]["pid"], clock)
                admit(clock)
                maybe_boost(clock)
            continue

        pid = queues[active_queue].pop(0)
        if remaining[pid] <= 1e-9:
            continue
        proc = by_pid[pid]
        lvl = level[pid]
        quantum = quantum_at_level[lvl]
        allotment_left = quantum - used_at_level[pid]
        run_time = min(allotment_left, remaining[pid])

        start = clock
        end = start + run_time
        gantt.append({"pid": pid, "name": proc.get("name"), "start": round(start, 2), "end": round(end, 2)})
        dispatch_order.append(pid)
        remaining[pid] -= run_time
        used_at_level[pid] += run_time
        clock = end

        admit(clock)
        maybe_boost(clock)

        if remaining[pid] <= 1e-9:
            continue  # job finished

        if level.get(pid, lvl) == lvl and used_at_level[pid] >= quantum - 1e-9:
            # Rule 4: allotment exhausted at this level -> demote one level.
            new_lvl = min(lvl + 1, num_queues - 1)
            level[pid] = new_lvl
            used_at_level[pid] = 0.0
            queues[new_lvl].append(pid)
        elif level.get(pid, lvl) == lvl:
            # Still has allotment left at this level (e.g. was preempted by
            # a boost) -- requeue at the SAME level with accounting intact
            # (rule 4's anti-gaming clause: no reset just because it didn't
            # run to the natural end of its quantum).
            queues[lvl].append(pid)
        else:
            # Already moved by a boost while running; respect its new level.
            queues[level[pid]].append(pid)

    metrics = _build_metrics(by_pid, gantt, arrivals)
    return {
        "algorithm": "mlfq",
        "order": dispatch_order,
        "gantt": gantt,
        "metrics": metrics,
        "config": {"num_queues": num_queues, "base_quantum": base_quantum, "boost_interval": boost_interval},
    }


ALGORITHMS = {
    "fcfs": fcfs,
    "sjf": sjf,
    "priority": priority_scheduling,
    "round_robin": round_robin,
    "eevdf": eevdf,
    "mlfq": mlfq,
}


def run_schedule(
    algorithm: str,
    processes: list[dict[str, Any]],
    quantum: int = 4,
    num_queues: int = 3,
    boost_interval: float = 50.0,
) -> dict[str, Any]:
    algorithm = algorithm.lower()
    if algorithm not in ALGORITHMS:
        raise ValueError(f"Unknown algorithm: {algorithm}. Choose from {sorted(ALGORITHMS)}")
    if algorithm == "round_robin":
        return round_robin(processes, quantum=quantum)
    if algorithm == "eevdf":
        return eevdf(processes, base_slice=float(quantum))
    if algorithm == "mlfq":
        return mlfq(processes, num_queues=num_queues, base_quantum=float(quantum), boost_interval=boost_interval)
    return ALGORITHMS[algorithm](processes)
