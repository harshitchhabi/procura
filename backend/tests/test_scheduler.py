"""Scheduler tests against hand-worked textbook-style examples.

Shared example processes (arrival, burst):
    P1: arrival=0, burst=5
    P2: arrival=1, burst=3
    P3: arrival=2, burst=8
    P4: arrival=3, burst=6
"""

from os_sim.scheduler import (
    fcfs, sjf, round_robin, priority_scheduling, effective_priority_score,
    eevdf, mlfq, jains_fairness_index, run_schedule,
)


def make_processes():
    return [
        {"pid": 1, "name": "P1", "arrival_time": 0, "burst_time": 5, "priority": "Medium",
         "memory_requirement": 0, "cpu_requirement": 0, "deadline": None},
        {"pid": 2, "name": "P2", "arrival_time": 1, "burst_time": 3, "priority": "Medium",
         "memory_requirement": 0, "cpu_requirement": 0, "deadline": None},
        {"pid": 3, "name": "P3", "arrival_time": 2, "burst_time": 8, "priority": "Medium",
         "memory_requirement": 0, "cpu_requirement": 0, "deadline": None},
        {"pid": 4, "name": "P4", "arrival_time": 3, "burst_time": 6, "priority": "Medium",
         "memory_requirement": 0, "cpu_requirement": 0, "deadline": None},
    ]


def metrics_by_pid(result):
    return {row["pid"]: row for row in result["metrics"]["per_process"]}


def test_fcfs_hand_worked():
    result = fcfs(make_processes())
    assert result["order"] == [1, 2, 3, 4]

    m = metrics_by_pid(result)
    assert m[1]["completion_time"] == 5
    assert m[2]["completion_time"] == 8
    assert m[3]["completion_time"] == 16
    assert m[4]["completion_time"] == 22

    assert m[1]["waiting_time"] == 0
    assert m[2]["waiting_time"] == 4
    assert m[3]["waiting_time"] == 6
    assert m[4]["waiting_time"] == 13

    assert result["metrics"]["average_waiting_time"] == 5.75


def test_sjf_hand_worked():
    result = sjf(make_processes())
    # Ascending burst time: P2(3), P1(5), P4(6), P3(8)
    assert result["order"] == [2, 1, 4, 3]

    m = metrics_by_pid(result)
    assert m[2]["completion_time"] == 4
    assert m[1]["completion_time"] == 9
    assert m[4]["completion_time"] == 15
    assert m[3]["completion_time"] == 23

    assert m[2]["waiting_time"] == 0
    assert m[1]["waiting_time"] == 4
    assert m[4]["waiting_time"] == 6
    assert m[3]["waiting_time"] == 13

    assert result["metrics"]["average_waiting_time"] == 5.75


def test_round_robin_hand_worked():
    result = round_robin(make_processes(), quantum=4)

    m = metrics_by_pid(result)
    assert m[1]["completion_time"] == 16
    assert m[2]["completion_time"] == 7
    assert m[3]["completion_time"] == 20
    assert m[4]["completion_time"] == 22

    assert m[1]["waiting_time"] == 11
    assert m[2]["waiting_time"] == 3
    assert m[3]["waiting_time"] == 10
    assert m[4]["waiting_time"] == 13

    assert m[1]["response_time"] == 0
    assert m[2]["response_time"] == 3
    assert m[3]["response_time"] == 5
    assert m[4]["response_time"] == 8

    assert result["metrics"]["average_waiting_time"] == 9.25


def test_priority_orders_by_effective_score_desc():
    processes = make_processes()
    processes[0]["priority"] = "Low"
    processes[1]["priority"] = "High"
    processes[2]["priority"] = "Low"
    processes[3]["priority"] = "Medium"

    result = priority_scheduling(processes)
    scores = {p["pid"]: effective_priority_score(p) for p in processes}
    expected_order = sorted(scores, key=lambda pid: -scores[pid])
    assert result["order"] == expected_order


def test_effective_priority_score_components():
    high = {"priority": "High", "deadline": None, "ready_since": None,
            "memory_requirement": 0, "cpu_requirement": 0}
    low = {"priority": "Low", "deadline": None, "ready_since": None,
           "memory_requirement": 0, "cpu_requirement": 0}
    assert effective_priority_score(high) > effective_priority_score(low)


def test_cpu_utilization_is_full_with_no_gaps():
    result = fcfs(make_processes())
    # No idle time between arrivals (P1 starts at 0 and each subsequent
    # process is ready before the previous finishes), so utilization is 100%.
    assert result["metrics"]["cpu_utilization"] == 100.0


# ---------------------------------------------------------------------------
# Jain's Fairness Index -- f(x) = (sum(x))^2 / (n * sum(x_i^2)), range [1/n, 1]
# ---------------------------------------------------------------------------


def test_jains_fairness_index_equal_allocation_is_one():
    assert jains_fairness_index([10, 10, 10, 10]) == 1.0


def test_jains_fairness_index_one_process_gets_everything():
    n = 4
    values = [40, 0, 0, 0]
    assert jains_fairness_index(values) == 1 / n


def test_jains_fairness_index_empty_is_zero():
    assert jains_fairness_index([]) == 0.0


def test_every_algorithm_reports_fairness_index():
    for result in (
        fcfs(make_processes()),
        sjf(make_processes()),
        priority_scheduling(make_processes()),
        round_robin(make_processes()),
        eevdf(make_processes()),
        mlfq(make_processes()),
    ):
        assert "fairness_index" in result["metrics"]
        assert 0.0 <= result["metrics"]["fairness_index"] <= 1.0


# ---------------------------------------------------------------------------
# EEVDF / MLFQ -- shape and basic sanity checks
# ---------------------------------------------------------------------------


def test_eevdf_produces_same_output_shape_and_conserves_burst_time():
    result = eevdf(make_processes())
    assert result["algorithm"] == "eevdf"
    total_gantt = sum(s["end"] - s["start"] for s in result["gantt"])
    assert total_gantt == sum(p["burst_time"] for p in make_processes())
    assert set(result["order"]) == {1, 2, 3, 4}
    assert len(result["metrics"]["per_process"]) == 4


def test_mlfq_produces_same_output_shape_and_conserves_burst_time():
    result = mlfq(make_processes())
    assert result["algorithm"] == "mlfq"
    total_gantt = sum(s["end"] - s["start"] for s in result["gantt"])
    assert total_gantt == sum(p["burst_time"] for p in make_processes())
    assert set(result["order"]) == {1, 2, 3, 4}


def test_mlfq_demotes_long_job_below_short_jobs_response_time():
    # A long job should fall to a lower queue after exhausting its
    # allotment, so later-arriving short jobs are not forced to wait a
    # full long-job burst behind it (unlike FCFS).
    result = mlfq(make_processes(), base_quantum=4, num_queues=3, boost_interval=50)
    m = {row["pid"]: row for row in result["metrics"]["per_process"]}
    # P3 (burst=8) needs more than one quantum and gets demoted; P2 (burst=3)
    # fits in a single quantum at the top queue and should finish quickly.
    assert m[2]["completion_time"] < m[3]["completion_time"]


def test_run_schedule_accepts_eevdf_and_mlfq():
    assert run_schedule("eevdf", make_processes())["algorithm"] == "eevdf"
    assert run_schedule("mlfq", make_processes())["algorithm"] == "mlfq"


# ---------------------------------------------------------------------------
# Fair-share decay term in effective_priority_score
# ---------------------------------------------------------------------------


def test_fair_share_penalizes_heavy_historical_consumer():
    heavy = {"priority": "Medium", "deadline": None, "ready_since": None,
             "memory_requirement": 0, "cpu_requirement": 0, "cumulative_cpu_time": 100.0}
    light = {"priority": "Medium", "deadline": None, "ready_since": None,
             "memory_requirement": 0, "cpu_requirement": 0, "cumulative_cpu_time": 0.0}
    all_procs = [heavy, light]
    assert effective_priority_score(heavy, all_processes=all_procs) < effective_priority_score(light, all_processes=all_procs)


def test_fair_share_defaults_to_zero_when_no_usage_tracked():
    # Backward compatibility: processes without cumulative_cpu_time behave
    # exactly as before the fair-share term was added.
    proc = {"priority": "Medium", "deadline": None, "ready_since": None,
            "memory_requirement": 0, "cpu_requirement": 0}
    assert effective_priority_score(proc) == effective_priority_score(proc, all_processes=[proc])
