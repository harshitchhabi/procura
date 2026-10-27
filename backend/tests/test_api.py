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


def test_ask_grounds_answer_in_recorded_incident():
    import database

    pid = client.post("/processes", json={"name": "Grounding probe", "burst_time": 10}).json()["pid"]
    error_id = database.log_error(pid, "memory_failure", "requires 1600MB memory but only 248.0MB is available.")
    database.log_recovery_action(error_id, "suspend_and_retry", pid)

    body = client.post("/ask", json={"question": "Why did this task fail?", "pid": pid}).json()

    assert "requires 1600MB memory but only 248.0MB is available." in body["answer"]
    assert "suspend_and_retry" in body["answer"]
    assert "Current simulated resources (now, after any recovery actions" in body["answer"]


def test_ask_explains_deadlock_victim_with_rule_and_cycle():
    import database

    a = client.post("/processes", json={"name": "Deadlock A", "burst_time": 10, "priority": "High"}).json()["pid"]
    b = client.post("/processes", json={"name": "Deadlock B", "burst_time": 10, "priority": "Low"}).json()["pid"]
    error_id = database.log_error(a, "deadlock", f"Circular wait detected among pids: {a} -> {b} -> {a}.")
    database.log_recovery_action(error_id, "terminate_and_resume", b)

    body = client.post("/ask", json={"question": "Why was this terminated?", "pid": b}).json()

    assert f"{a} -> {b} -> {a}" in body["answer"]
    assert "lowest effective priority in the cycle" in body["answer"]


def test_incident_facts_label_every_pool_with_its_unit():
    facts = main._incident_facts_for(client.post("/processes", json={"name": "Units probe", "burst_time": 5}).json()["pid"])
    pools = facts[-1]
    for unit in ("MB of memory", "% of CPU", "file handles", "database connections", "Mbps of network bandwidth"):
        assert unit in pools


def test_prompt_tells_the_model_to_use_units_and_not_claim_a_single_option():
    from rag.assistant import _build_prompt

    prompt = _build_prompt("q", [], None, ["fact"])
    assert "never invent a unit" in prompt
    assert "only possible one" in prompt


# --- provider failures must be retried and reported, never silently become "no key" ---

class _FakeResp:
    def __init__(self, status, body=None, text="", headers=None):
        self.status_code, self._body, self.text, self.headers = status, body or {}, text, headers or {}

    def json(self):
        return self._body


def test_post_json_waits_for_the_providers_hint_then_succeeds(monkeypatch):
    import httpx
    from rag import assistant

    calls, sleeps = [], []
    replies = [
        _FakeResp(429, text='{"error":{"message":"Please try again in 4.7s."}}'),
        _FakeResp(200, {"choices": [{"message": {"content": "ok"}}]}),
    ]
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append(1) or replies[len(calls) - 1])
    monkeypatch.setattr(assistant.time, "sleep", sleeps.append)

    data, reason = assistant._post_json("https://x", {}, {})

    assert reason is None and data["choices"][0]["message"]["content"] == "ok"
    assert len(calls) == 2 and 5.0 <= sleeps[0] <= 5.3  # 4.7 s hint + 0.5 s margin


def test_post_json_gives_up_with_a_reason(monkeypatch):
    import httpx
    from rag import assistant

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResp(429, headers={"retry-after": "2"}))
    monkeypatch.setattr(assistant.time, "sleep", lambda s: None)
    assert assistant._post_json("https://x", {}, {}, attempts=3) == (None, "rate_limited")

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResp(401))
    assert assistant._post_json("https://x", {}, {}, attempts=3) == (None, "http_401")


def test_answer_reports_why_a_configured_model_did_not_answer(monkeypatch):
    from rag import assistant

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(assistant, "_call_groq", lambda prompt, key: (None, "rate_limited"))
    out = assistant.answer_question("What is the convoy effect?")

    assert out["mode"] == "offline_extractive"
    assert out["fallback_reason"] == "groq: rate_limited"
    assert "did not answer (groq: rate_limited)" in out["answer"]
    assert "no LLM API key configured" not in out["answer"]


def test_empty_reasoning_answer_is_reported_not_hidden(monkeypatch):
    import httpx
    from rag import assistant

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResp(200, {"choices": [{"message": {"content": ""}}]}))
    assert assistant._call_groq("p", "k") == (None, "empty_answer")


def test_demo_reset_restores_the_seeded_state():
    client.post("/processes", json={"name": "Extra task", "burst_time": 5})
    client.post("/resources/allocate", json={"pid": 1, "resource": "file", "amount": 64})
    client.post("/resources/allocate", json={"pid": 3, "resource": "database", "amount": 20})
    client.post("/resources/allocate", json={"pid": 1, "resource": "database", "amount": 5})
    client.post("/resources/allocate", json={"pid": 3, "resource": "file", "amount": 5})
    assert client.get("/resources").json()["waiting_for_graph"]

    resp = client.post("/demo/reset")
    assert resp.status_code == 200 and resp.json() == {"reset": True, "processes": 6}

    res = client.get("/resources").json()
    assert res["waiting_for_graph"] == {}
    assert all(u["allocated"] == 0 for u in res["utilization"].values())
    procs = client.get("/processes").json()
    assert len(procs) == 6 and {p["state"] for p in procs} == {"READY"}
    assert client.get("/errors").json() == []
