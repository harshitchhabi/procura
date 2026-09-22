"""Scheduler tests against hand-worked textbook-style examples.

Shared example processes (arrival, burst):
    P1: arrival=0, burst=5
    P2: arrival=1, burst=3
    P3: arrival=2, burst=8
    P4: arrival=3, burst=6
"""

from os_sim.scheduler import fcfs, sjf, round_robin, priority_scheduling, effective_priority_score


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
