"""Tests for the benchmark module: SWF parsing and metric functions."""

from pathlib import Path

from benchmark import metrics, workload

SAMPLE_SWF = Path(__file__).resolve().parent.parent / "benchmark" / "sample_traces" / "sample.swf"


def test_parse_swf_reads_all_jobs_and_skips_comments():
    jobs = workload.parse_swf(str(SAMPLE_SWF))
    assert len(jobs) == 15
    assert jobs[0]["job_number"] == 1
    assert jobs[0]["submit_time"] == 0
    assert jobs[0]["run_time"] == 120
    # 18 fields parsed per job.
    assert len(jobs[0]) == 18


def test_parse_swf_handles_inapplicable_minus_one_fields():
    jobs = workload.parse_swf(str(SAMPLE_SWF))
    # application_id column is -1 ("inapplicable") for every sample job.
    assert all(j["application_id"] == -1 for j in jobs)


def test_swf_to_processes_maps_onto_scheduler_schema():
    jobs = workload.parse_swf(str(SAMPLE_SWF))
    processes = workload.swf_to_processes(jobs)
    assert len(processes) == len(jobs)
    first = processes[0]
    assert set(["pid", "name", "arrival_time", "burst_time", "priority"]) <= set(first.keys())
    assert first["arrival_time"] == 0  # earliest submit_time normalized to 0
    assert first["burst_time"] == 120


def test_generate_poisson_workload_is_deterministic_with_seed():
    a = workload.generate_poisson_workload(n=10, seed=7)
    b = workload.generate_poisson_workload(n=10, seed=7)
    assert a == b
    assert len(a) == 10
    # Arrivals must be non-decreasing (Poisson process timeline).
    arrivals = [p["arrival_time"] for p in a]
    assert arrivals == sorted(arrivals)


def test_makespan_hand_computed():
    gantt = [
        {"pid": 1, "start": 0, "end": 5},
        {"pid": 2, "start": 5, "end": 8},
        {"pid": 3, "start": 8, "end": 16},
    ]
    assert metrics.makespan(gantt) == 16


def test_utilization_hand_computed_no_idle_time():
    # Three consecutive jobs with no gaps -> fully utilized single machine.
    gantt = [
        {"pid": 1, "start": 0, "end": 5},
        {"pid": 2, "start": 5, "end": 8},
        {"pid": 3, "start": 8, "end": 16},
    ]
    assert metrics.utilization(gantt, num_machines=1) == 1.0


def test_utilization_hand_computed_with_idle_gap():
    # Busy time = 5 + 3 = 8, makespan = 10 (2-unit idle gap) -> utilization 0.8
    gantt = [
        {"pid": 1, "start": 0, "end": 5},
        {"pid": 2, "start": 7, "end": 10},
    ]
    assert metrics.utilization(gantt, num_machines=1) == 0.8


def test_starvation_metrics_counts_exceeding_threshold():
    per_process = [
        {"waiting_time": 5},
        {"waiting_time": 40},
        {"waiting_time": 50},
    ]
    result = metrics.starvation_metrics(per_process, threshold=30.0)
    assert result["max_wait"] == 50
    assert result["exceeding_count"] == 2
    assert result["exceeding_rate"] == 2 / 3
