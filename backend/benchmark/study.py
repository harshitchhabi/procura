"""Multi-seed statistical study of the six scheduling policies.

A single seeded run (run_benchmark.py) shows one workload. This runs every
policy on many independent workloads, in three workload families and several
sizes and loads, and reports each metric as a mean with a 95% confidence
interval, plus paired differences against FCFS (the same workload is given to
every policy, so differences are paired and much tighter than unpaired ones).

Usage (from backend/):
    python -m benchmark.study                 # full study, writes benchmark/results/study.json
    python -m benchmark.study --quick         # small smoke run
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark.workload import WORKLOAD_KINDS, generate_workload
from os_sim.scheduler import run_schedule

ALGORITHMS = ["fcfs", "sjf", "priority", "round_robin", "eevdf", "mlfq"]
STARVE_THRESHOLD = 30.0
RESULTS = Path(__file__).resolve().parent / "results"

METRICS = {
    "avg_wait": "mean waiting time (min)",
    "max_wait": "maximum waiting time (min)",
    "avg_response": "mean response time (min)",
    "avg_slowdown": "mean bounded slowdown",
    "max_slowdown": "maximum bounded slowdown",
    "delay_fairness": "Jain's index over 1/slowdown",
    "starved": "share of jobs waiting > 30 min",
}


def t_critical(df: int) -> float:
    """Two-sided 95% Student-t critical value (Cornish-Fisher expansion; error < 0.001 for df >= 10)."""
    z = 1.959964
    return z + (z**3 + z) / (4 * df) + (5 * z**5 + 16 * z**3 + 3 * z) / (96 * df**2)


def mean_ci(values: list[float]) -> tuple[float, float]:
    """Mean and 95% confidence half-width."""
    n = len(values)
    m = statistics.fmean(values)
    if n < 2:
        return m, 0.0
    return m, t_critical(n - 1) * statistics.stdev(values) / n**0.5


def one_run(kind: str, n: int, load: float, seed: int) -> dict[str, dict[str, float]]:
    jobs = generate_workload(kind, n, load, seed)
    out: dict[str, dict[str, float]] = {}
    for algo in ALGORITHMS:
        m = run_schedule(algo, [dict(j) for j in jobs])["metrics"]
        per = m["per_process"]
        waits = [p["waiting_time"] for p in per]
        out[algo] = {
            "avg_wait": m["average_waiting_time"],
            "max_wait": max(waits),
            "avg_response": m["average_response_time"],
            "avg_slowdown": m["average_bounded_slowdown"],
            "max_slowdown": m["max_bounded_slowdown"],
            "delay_fairness": m["delay_fairness_index"],
            "starved": sum(w > STARVE_THRESHOLD for w in waits) / len(waits),
        }
    return out


def study(kind: str, n: int, load: float, seeds: int) -> dict[str, Any]:
    runs = [one_run(kind, n, load, seed) for seed in range(1, seeds + 1)]
    summary: dict[str, Any] = {"kind": kind, "n": n, "load": load, "seeds": seeds, "algorithms": {}}
    for algo in ALGORITHMS:
        row: dict[str, Any] = {}
        for metric in METRICS:
            vals = [r[algo][metric] for r in runs]
            mean, half = mean_ci(vals)
            row[metric] = {"mean": mean, "ci": half}
            if algo != "fcfs":
                diffs = [r[algo][metric] - r["fcfs"][metric] for r in runs]
                dm, dh = mean_ci(diffs)
                row[metric]["vs_fcfs"] = {"mean": dm, "ci": dh, "significant": abs(dm) > dh}
        summary["algorithms"][algo] = row
    return summary


def fmt(cell: dict[str, float], digits: int = 1) -> str:
    return f"{cell['mean']:.{digits}f} ± {cell['ci']:.{digits}f}"


def print_study(s: dict[str, Any]) -> None:
    print(f"\n=== {s['kind']}, n={s['n']}, load={s['load']}, {s['seeds']} seeds (mean ± 95% CI) ===")
    cols = [("avg_wait", 1), ("max_wait", 1), ("avg_response", 1), ("avg_slowdown", 2), ("delay_fairness", 3), ("starved", 3)]
    print("algorithm".ljust(13) + "".join(m.ljust(18) for m, _ in cols))
    for algo in ALGORITHMS:
        row = s["algorithms"][algo]
        print(algo.ljust(13) + "".join(fmt(row[m], d).ljust(18) for m, d in cols))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Multi-seed study of the six scheduling policies.")
    ap.add_argument("--quick", action="store_true", help="Few seeds and small sizes, for a smoke test.")
    ap.add_argument("--out", default=str(RESULTS / "study.json"))
    args = ap.parse_args()

    if args.quick:
        plan = [("gamma", 30, 0.9, 5)]
        sweep = [("gamma", 30, 0.7, 5)]
    else:
        plan = [(k, n, 0.9, 50 if n <= 100 else 25) for k in WORKLOAD_KINDS for n in (30, 100, 300)]
        sweep = [("gamma", 100, load, 30) for load in (0.5, 0.7, 0.9, 1.2)]

    t0 = time.time()
    families = []
    for kind, n, load, seeds in plan:
        s = study(kind, n, load, seeds)
        families.append(s)
        print_study(s)
        print(f"  ({time.time() - t0:.0f}s elapsed)", flush=True)
    sweeps = []
    for kind, n, load, seeds in sweep:
        s = study(kind, n, load, seeds)
        sweeps.append(s)
        print_study(s)
        print(f"  ({time.time() - t0:.0f}s elapsed)", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"families": families, "load_sweep": sweeps, "metrics": METRICS}, indent=1), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
