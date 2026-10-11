from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_and_list_process():
    resp = client.post(
        "/processes",
        json={"name": "API test task", "burst_time": 15, "priority": "High", "memory_requirement": 100},
    )
    assert resp.status_code == 200
    created = resp.json()
    assert created["state"] == "READY"

    resp = client.get("/processes")
    assert resp.status_code == 200
    pids = [p["pid"] for p in resp.json()]
    assert created["pid"] in pids


def test_process_action_transition():
    created = client.post("/processes", json={"name": "Action test", "burst_time": 5}).json()
    resp = client.patch(f"/processes/{created['pid']}", json={"action": "start"})
    assert resp.status_code == 200
    assert resp.json()["state"] == "RUNNING"


def test_invalid_transition_returns_409():
    created = client.post("/processes", json={"name": "Bad transition", "burst_time": 5}).json()
    resp = client.patch(f"/processes/{created['pid']}", json={"action": "complete"})
    assert resp.status_code == 409


def test_schedule_endpoint():
    client.post("/processes", json={"name": "Sched A", "burst_time": 5})
    client.post("/processes", json={"name": "Sched B", "burst_time": 3})
    resp = client.get("/schedule", params={"algorithm": "sjf"})
    assert resp.status_code == 200
    body = resp.json()
    assert "gantt" in body and "metrics" in body


def test_ask_endpoint_offline_fallback():
    resp = client.post("/ask", json={"question": "What is a deadlock?"})
    assert resp.status_code == 200
    body = resp.json()
    assert "answer" in body
    assert body["mode"] in ("offline_extractive", "groq", "anthropic", "openai")


def test_resources_endpoint():
    resp = client.get("/resources")
    assert resp.status_code == 200
    body = resp.json()
    assert "utilization" in body
    assert "cpu" in body["utilization"]


def test_schedule_endpoint_accepts_eevdf():
    client.post("/processes", json={"name": "EEVDF A", "burst_time": 5})
    client.post("/processes", json={"name": "EEVDF B", "burst_time": 3, "priority": "High"})
    resp = client.get("/schedule", params={"algorithm": "eevdf"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["algorithm"] == "eevdf"
    assert "fairness_index" in body["metrics"]


def test_schedule_endpoint_accepts_mlfq():
    client.post("/processes", json={"name": "MLFQ A", "burst_time": 5})
    client.post("/processes", json={"name": "MLFQ B", "burst_time": 3, "priority": "High"})
    resp = client.get("/schedule", params={"algorithm": "mlfq"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["algorithm"] == "mlfq"
    assert "fairness_index" in body["metrics"]


def test_benchmark_endpoint_returns_all_six_algorithms():
    resp = client.get("/benchmark", params={"n": 10})
    assert resp.status_code == 200
    body = resp.json()
    algos = {row["algorithm"] for row in body["results"]}
    assert algos == {"fcfs", "sjf", "priority", "round_robin", "eevdf", "mlfq"}
