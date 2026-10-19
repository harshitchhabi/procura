"""Error detection: burst-time anomalies, memory allocation failures, deadlocks.

Burst-time anomaly detection ("is this process hogging the CPU") originally
used a naive fixed threshold (ran >1.5x its declared burst time). Per the
research report ("Statistical detection beats thresholds" section, citing
NIST's SEMATECH Handbook), that style of fixed-threshold rule is exactly
what production monitoring has moved away from. This module now implements
the three NIST-specified statistical process control (SPC) methods the
report calls out -- EWMA, Modified Z-score, and CUSUM -- against a rolling
in-memory history of burst-time-vs-actual-time ratios, with the legacy
fixed-threshold rule kept as an explicit, clearly-labeled fallback/mode.

The memory_failure and deadlock detectors are untouched: they are not
threshold-based anomaly detection, they are direct structural checks
(capacity exceeded / cycle in the waits-for graph), which the report does
not ask us to change.
"""

from __future__ import annotations

import statistics
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

from os_sim.resource_manager import ResourceManager

ANOMALY_MULTIPLIER = 1.5
HIGH_CPU_THRESHOLD = 80.0  # percent of CPU pool considered "high usage"

# ---------------------------------------------------------------------------
# Rolling baseline of burst-time-vs-actual ratios, keyed by pid. A ratio of
# 1.0 means "running exactly as long as declared"; >1 means running longer.
# This is the "stable mean" baseline the NIST SPC methods need -- kept as a
# rolling window (not one fixed historical mean) per the report's explicit
# caveat that IT metrics lack SPC's foundational stable-mean assumption and
# so should be paired with a rolling re-baselining window.
# ---------------------------------------------------------------------------

ROLLING_WINDOW = 30
_history: dict[int, deque] = {}


def reset_history() -> None:
    """Testing/debug hook: clear all rolling anomaly-detection history."""
    _history.clear()


def _record_ratio(pid: int, ratio: float) -> deque:
    hist = _history.setdefault(pid, deque(maxlen=ROLLING_WINDOW))
    hist.append(ratio)
    return hist


# ---------------------------------------------------------------------------
# EWMA (NIST Handbook section 6.3.2.4): EWMA_t = lambda*Y_t + (1-lambda)*EWMA_{t-1}
# Control limits: EWMA_0 +/- k*s_ewma, where s_ewma^2 = (lambda/(2-lambda))*s^2.
# Default lambda=0.2-0.3, k=3 per the report.
# ---------------------------------------------------------------------------


def ewma_flag(history: list[float], new_value: float, lam: float = 0.25, k: float = 3.0) -> tuple[bool, dict[str, float]]:
    if len(history) < 2:
        return False, {"ewma": new_value, "upper": float("inf"), "lower": float("-inf")}
    target = statistics.mean(history)
    s = statistics.pstdev(history) or 1e-9
    ewma = history[0]
    for y in history[1:]:
        ewma = lam * y + (1 - lam) * ewma
    ewma = lam * new_value + (1 - lam) * ewma
    s_ewma = ((lam / (2 - lam)) * s * s) ** 0.5
    upper = target + k * s_ewma
    lower = target - k * s_ewma
    return (ewma > upper or ewma < lower), {"ewma": ewma, "upper": upper, "lower": lower}


# ---------------------------------------------------------------------------
# Modified Z-score (NIST Handbook section 1.3.5.17). NIST explicitly does
# NOT endorse the naive |Z|>2/3 rule-of-thumb; it recommends the
# median/MAD-based modified version instead: M_i = 0.6745*(x_i - median)/MAD,
# flag if |M_i| > 3.5.
# ---------------------------------------------------------------------------


def modified_zscore_flag(history: list[float], new_value: float, threshold: float = 3.5) -> tuple[bool, dict[str, float]]:
    sample = list(history) + [new_value]
    if len(sample) < 2:
        return False, {"modified_z": 0.0}
    median = statistics.median(sample)
    mad = statistics.median([abs(x - median) for x in sample]) or 1e-9
    m_i = 0.6745 * (new_value - median) / mad
    return abs(m_i) > threshold, {"modified_z": m_i}


# ---------------------------------------------------------------------------
# CUSUM (NIST Handbook section 6.3.2.3): two-sided cumulative sum recursion.
# S_hi = max(0, S_hi_prev + (x_i - target - k))
# S_lo = max(0, S_lo_prev - (x_i - target + k))
# Flag when either crosses the decision interval h.
# k and h are derivable from a desired shift size (delta), false-alarm rate
# (alpha), and miss rate (beta); we expose sensible defaults (k = delta/2 in
# units of sigma, h = 5*sigma is the NIST-cited conventional choice) rather
# than requiring the caller to specify alpha/beta directly.
# ---------------------------------------------------------------------------


def cusum_flag(
    history: list[float],
    new_value: float,
    shift_sigma: float = 1.0,
    h_sigma: float = 5.0,
) -> tuple[bool, dict[str, float]]:
    if len(history) < 2:
        return False, {"s_hi": 0.0, "s_lo": 0.0}
    target = statistics.mean(history)
    sigma = statistics.pstdev(history) or 1e-9
    k = (shift_sigma * sigma) / 2.0  # reference value, NIST's recommended delta/2 rule
    h = h_sigma * sigma  # decision interval

    s_hi = 0.0
    s_lo = 0.0
    for y in history:
        s_hi = max(0.0, s_hi + (y - target - k))
        s_lo = max(0.0, s_lo - (y - target + k))
    s_hi = max(0.0, s_hi + (new_value - target - k))
    s_lo = max(0.0, s_lo - (new_value - target + k))

    return (s_hi > h or s_lo > h), {"s_hi": s_hi, "s_lo": s_lo, "h": h}


DETECTION_METHODS = {"ewma", "modified_zscore", "cusum", "fixed_threshold"}


def detect_burst_anomaly(
    process: dict[str, Any],
    actual_running_minutes: float,
    resource_mgr: ResourceManager,
    method: str = "ewma",
) -> Optional[dict[str, Any]]:
    """Flag a process as anomalous if its burst-time-vs-actual ratio is a
    statistical outlier relative to its own rolling history (or, in
    `fixed_threshold` mode, the original naive 1.5x rule kept for backward
    compatibility/comparison).

    Default method is EWMA, per the research report framing it as "the most
    broadly-applicable" of the three NIST-specified methods.
    """
    burst = process.get("burst_time", 0)
    if burst <= 0:
        return None
    pid = process["pid"]
    cpu_util = resource_mgr.utilization()["cpu"]["utilization_pct"]
    ratio = actual_running_minutes / burst

    if method == "fixed_threshold":
        if actual_running_minutes > burst * ANOMALY_MULTIPLIER and cpu_util >= HIGH_CPU_THRESHOLD:
            return {
                "error_type": "burst_anomaly",
                "pid": pid,
                "method": "fixed_threshold",
                "details": (
                    f"pid {pid} ({process.get('name')}) has run {actual_running_minutes:.1f} min, "
                    f"exceeding 1.5x its declared burst_time of {burst} min, while CPU utilization is {cpu_util}%."
                ),
            }
        return None

    if method not in DETECTION_METHODS:
        raise ValueError(f"Unknown detection method: {method}. Choose from {sorted(DETECTION_METHODS)}")

    history = list(_history.get(pid, deque(maxlen=ROLLING_WINDOW)))
    _record_ratio(pid, ratio)

    if method == "ewma":
        flagged, stats = ewma_flag(history, ratio)
    elif method == "modified_zscore":
        flagged, stats = modified_zscore_flag(history, ratio)
    else:  # cusum
        flagged, stats = cusum_flag(history, ratio)

    if flagged:
        return {
            "error_type": "burst_anomaly",
            "pid": pid,
            "method": method,
            "details": (
                f"pid {pid} ({process.get('name')}) burst-time ratio {ratio:.2f} flagged as a "
                f"statistical anomaly by {method} (stats: {stats}), CPU utilization {cpu_util}%."
            ),
        }
    return None


def detect_memory_failure(process: dict[str, Any], resource_mgr: ResourceManager) -> Optional[dict[str, Any]]:
    """Flag a memory_failure if a process's declared memory_requirement
    exceeds what's currently available in the memory pool."""
    requirement = process.get("memory_requirement", 0)
    already_held = resource_mgr.holders.get("memory", {}).get(process["pid"], 0)
    if already_held >= requirement:
        return None
    available = resource_mgr.available("memory")
    if requirement - already_held > available:
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


def run_detection(
    processes: list[dict[str, Any]],
    resource_mgr: ResourceManager,
    anomaly_method: str = "ewma",
) -> list[dict[str, Any]]:
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
            anomaly = detect_burst_anomaly(proc, running_minutes, resource_mgr, method=anomaly_method)
            if anomaly:
                findings.append(anomaly)

    return findings
