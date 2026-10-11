"""Run all six scheduling algorithms against an identical workload and print
a comparison table of the standard metrics (benchmark/metrics.py).

Usage (from backend/):
    python -m benchmark.run_benchmark
    python -m benchmark.run_benchmark --swf benchmark/sample_traces/sample.swf
    python -m benchmark.run_benchmark --n 30 --arrival-rate 0.4
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark import metrics, workload
from os_sim.scheduler import ALGORITHMS, run_schedule

ALL_ALGORITHMS = ["fcfs", "sjf", "priority", "round_robin", "eevdf", "mlfq"]


def run_all(processes: list[dict[str, Any]], quantum: int = 4) -> list[dict[str, Any]]:
    rows = []
    for algo in ALL_ALGORITHMS:
        result = run_schedule(algo, [dict(p) for p in processes], quantum=quantum)
        rows.append(metrics.summarize(result))
    return rows


def print_table(rows: list[dict[str, Any]]) -> None:
    headers = ["algorithm", "makespan", "avg_turnaround", "avg_waiting", "utilization", "fairness_index", "max_wait", "starved_count"]
    widths = [14, 10, 15, 12, 12, 15, 10, 14]
    line = "".join(h.ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("-" * sum(widths))
    for row in rows:
        starv = row["starvation"]
        values = [
            row["algorithm"],
            row["makespan"],
            row["average_turnaround_time"],
            row["average_waiting_time"],
            row["utilization"],
            row["fairness_index"],
            starv["max_wait"],
            starv["exceeding_count"],
        ]
        print("".join(str(v).ljust(w) for v, w in zip(values, widths)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark all 6 Procura scheduling algorithms.")
    parser.add_argument("--swf", type=str, default=None, help="Path to an SWF trace file (overrides synthetic generation).")
    parser.add_argument("--n", type=int, default=25, help="Number of synthetic jobs to generate.")
    parser.add_argument("--arrival-rate", type=float, default=0.3, help="Poisson arrival rate (jobs per minute).")
    parser.add_argument("--quantum", type=int, default=4, help="Base quantum/slice for round_robin, eevdf, mlfq.")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for synthetic workload.")
    args = parser.parse_args()

    if args.swf:
        jobs = workload.parse_swf(args.swf)
        processes = workload.swf_to_processes(jobs)
        print(f"Loaded {len(processes)} jobs from SWF trace: {args.swf}\n")
    else:
        processes = workload.generate_poisson_workload(n=args.n, arrival_rate=args.arrival_rate, seed=args.seed)
        print(f"Generated {len(processes)} synthetic jobs (Poisson arrivals, rate={args.arrival_rate}, seed={args.seed})\n")

    rows = run_all(processes, quantum=args.quantum)
    print_table(rows)


if __name__ == "__main__":
    main()
