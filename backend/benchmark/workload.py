"""Synthetic workload generation + Standard Workload Format (SWF) parsing.

Research report, "Benchmarking Procura against real traces" section:
  - The Parallel Workloads Archive (cs.huji.ac.il) defines SWF, a flat
    ASCII, 18-field, one-job-per-line format, with -1 for inapplicable
    fields.
  - Where real traces aren't available, the field-standard synthetic
    alternative is Poisson-arrival generation (exponential inter-arrival
    times) paired with the Lublin-Feitelson model, which uses hyper-Gamma
    distributions to jointly generate arrival time, requested parallelism,
    and runtime.

**Documented simplification** (the report notes exact Lublin-Feitelson
parameters weren't found in the research): we approximate it with a
straightforward Gamma distribution for burst/run times rather than
Lublin-Feitelson's full hyper-Gamma joint model. The report explicitly
says this is an acceptable starting point -- one comparative study found
relative algorithm rankings were largely unaffected by real vs. synthetic
workload choice.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Optional

PRIORITY_LABELS = ["High", "Medium", "Low"]

# 18 fields per the Parallel Workloads Archive SWF spec.
SWF_FIELDS = [
    "job_number",
    "submit_time",
    "wait_time",
    "run_time",
    "allocated_processors",
    "avg_cpu_time_used",
    "used_memory",
    "requested_processors",
    "requested_time",
    "requested_memory",
    "status",
    "user_id",
    "group_id",
    "application_id",
    "queue_id",
    "partition_id",
    "preceding_job_number",
    "think_time_from_preceding_job",
]


def generate_poisson_workload(
    n: int = 20,
    arrival_rate: float = 0.5,
    burst_shape: float = 2.0,
    burst_scale: float = 4.0,
    seed: Optional[int] = 42,
) -> list[dict[str, Any]]:
    """Generate `n` synthetic processes with:
      - Poisson arrivals: inter-arrival times ~ Exponential(arrival_rate),
        so arrivals form a Poisson process (research report's "field-standard
        synthetic alternative").
      - Burst/run times ~ Gamma(shape=burst_shape, scale=burst_scale) --
        our documented simplification of Lublin-Feitelson's hyper-Gamma
        model (see module docstring).

    Returns a list of process dicts in the shape os_sim.scheduler expects
    (pid, name, arrival_time, burst_time, priority, memory_requirement,
    cpu_requirement).
    """
    rng = random.Random(seed)
    processes = []
    clock = 0.0
    for i in range(1, n + 1):
        inter_arrival = rng.expovariate(arrival_rate)
        clock += inter_arrival
        burst = max(1.0, rng.gammavariate(burst_shape, burst_scale))
        priority = rng.choice(PRIORITY_LABELS)
        processes.append(
            {
                "pid": i,
                "name": f"job-{i}",
                "arrival_time": round(clock, 2),
                "burst_time": round(burst, 2),
                "priority": priority,
                "memory_requirement": rng.randint(0, 512),
                "cpu_requirement": rng.randint(0, 50),
            }
        )
    return processes


def parse_swf(path: str) -> list[dict[str, Any]]:
    """Parse a Standard Workload Format (SWF) trace file.

    SWF is a flat ASCII format, one job per line, 18 whitespace-separated
    integer fields (see SWF_FIELDS above), with -1 marking a field that
    does not apply to a given log. Lines starting with ';' are comments
    (SWF header metadata) and are skipped.

    Returns a list of raw SWF-field dicts (one per job), *and* the same
    dicts additionally carry a scheduler-compatible subset (pid,
    arrival_time, burst_time, priority) so the parsed trace can be fed
    directly into os_sim.scheduler.run_schedule via `swf_to_processes`.
    """
    jobs: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            values = [int(float(p)) for p in parts[: len(SWF_FIELDS)]]
            # Pad missing trailing fields with -1 (inapplicable), per spec.
            while len(values) < len(SWF_FIELDS):
                values.append(-1)
            jobs.append(dict(zip(SWF_FIELDS, values)))
    return jobs


def swf_to_processes(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map parsed SWF jobs onto Procura's scheduler process schema."""
    processes = []
    base_submit = min((j["submit_time"] for j in jobs), default=0)
    for j in jobs:
        run_time = j["run_time"] if j["run_time"] > 0 else 1
        processes.append(
            {
                "pid": j["job_number"],
                "name": f"swf-job-{j['job_number']}",
                "arrival_time": j["submit_time"] - base_submit,
                "burst_time": run_time,
                "priority": "Medium",
                "memory_requirement": max(0, j.get("used_memory", 0)),
                "cpu_requirement": 0,
            }
        )
    return processes
