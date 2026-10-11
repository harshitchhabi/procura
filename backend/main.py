"""Procura backend: FastAPI app exposing the process/scheduler/resource/RAG/recovery API.

Single-user, local-first, no auth. Run with:
    uvicorn main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import database
from benchmark import metrics as bench_metrics
from benchmark import workload as bench_workload
from os_sim import process_manager, scheduler
from os_sim.process_manager import ProcessNotFoundError
from os_sim.resource_manager import RESOURCE_NAMES, ResourceManager
from os_sim.states import InvalidTransitionError
from rag.assistant import answer_question
from recovery import diagnosis, recovery
from recovery.detector import run_detection

load_dotenv()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    database.init_db()
    yield


app = FastAPI(
    title="Procura",
    description="Task management reimagined as an OS process scheduler.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single in-memory resource manager shared across requests for the app's lifetime.
resource_manager = ResourceManager()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ProcessCreate(BaseModel):
    name: str
    description: str = ""
    priority: str = "Medium"
    deadline: Optional[str] = None
    burst_time: int = 10
    memory_requirement: int = 0
    cpu_requirement: int = 0
    arrival_time: Optional[str] = None


class ProcessAction(BaseModel):
    action: str = Field(description="One of: start, pause, resume, terminate, complete")


class AllocationRequest(BaseModel):
    pid: int
    resource: str
    amount: float


class AskRequest(BaseModel):
    question: str
    pid: Optional[int] = None


class AvoidanceModeRequest(BaseModel):
    enabled: bool


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------


@app.get("/processes")
def get_processes(state: Optional[str] = None) -> list[dict[str, Any]]:
    return process_manager.list_processes(state=state)


@app.post("/processes")
def post_process(body: ProcessCreate) -> dict[str, Any]:
    return process_manager.create_process(**body.model_dump())


@app.get("/processes/{pid}")
def get_process(pid: int) -> dict[str, Any]:
    try:
        return process_manager.get_process(pid)
    except ProcessNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


ACTION_MAP = {
    "start": process_manager.start_process,
    "pause": process_manager.pause_process,
    "resume": process_manager.resume_process,
    "terminate": process_manager.terminate_process,
    "complete": process_manager.complete_process,
}


@app.patch("/processes/{pid}")
def patch_process(pid: int, body: ProcessAction) -> dict[str, Any]:
    handler = ACTION_MAP.get(body.action)
    if handler is None:
        raise HTTPException(status_code=400, detail=f"Unknown action {body.action!r}. Choose from {sorted(ACTION_MAP)}")
    try:
        return handler(pid)
    except ProcessNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.delete("/processes/{pid}")
def delete_process(pid: int) -> dict[str, bool]:
    resource_manager.release_all_for_pid(pid)
    deleted = process_manager.delete_process(pid)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No process with pid {pid}")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


def _run_schedule(algorithm: str, quantum: int) -> dict[str, Any]:
    ready_processes = process_manager.list_processes(state="READY")
    if not ready_processes:
        # Fall back to all non-terminal processes so the page isn't empty when nothing is READY.
        ready_processes = [
            p for p in process_manager.list_processes()
            if p["state"] not in ("COMPLETED", "TERMINATED")
        ]
    try:
        return scheduler.run_schedule(algorithm, ready_processes, quantum=quantum)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/schedule")
def get_schedule(algorithm: str = "fcfs", quantum: int = 4) -> dict[str, Any]:
    return _run_schedule(algorithm, quantum)


@app.post("/schedule")
def post_schedule(algorithm: str = "fcfs", quantum: int = 4) -> dict[str, Any]:
    return _run_schedule(algorithm, quantum)


@app.get("/benchmark")
def get_benchmark(n: int = 24, arrival_rate: float = 0.3, seed: int = 42, quantum: int = 4) -> dict[str, Any]:
    """Run all six scheduling algorithms against an identical synthetic
    workload (Poisson arrivals, research report's "field-standard
    synthetic alternative") and return the standard comparison metrics
    (backend/benchmark/metrics.py) as JSON. Kept small (default 24 jobs)
    so it stays fast enough for a single HTTP request.
    """
    n = max(1, min(n, 60))
    processes = bench_workload.generate_poisson_workload(n=n, arrival_rate=arrival_rate, seed=seed)
    rows = []
    for algo in ("fcfs", "sjf", "priority", "round_robin", "eevdf", "mlfq"):
        result = scheduler.run_schedule(algo, [dict(p) for p in processes], quantum=quantum)
        rows.append(bench_metrics.summarize(result))
    return {"workload_size": n, "arrival_rate": arrival_rate, "seed": seed, "results": rows}


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@app.get("/resources")
def get_resources() -> dict[str, Any]:
    return {
        "utilization": resource_manager.utilization(),
        "waiting_for_graph": resource_manager.wait_graph(),
        "avoidance_mode": resource_manager.avoidance_mode,
    }


@app.post("/resources/allocate")
def allocate_resource(body: AllocationRequest) -> dict[str, Any]:
    if body.resource not in RESOURCE_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown resource {body.resource!r}. Choose from {RESOURCE_NAMES}")
    return resource_manager.allocate(body.pid, body.resource, body.amount)


@app.post("/resources/release")
def release_resource(body: AllocationRequest) -> dict[str, Any]:
    if body.resource not in RESOURCE_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown resource {body.resource!r}. Choose from {RESOURCE_NAMES}")
    return resource_manager.release(body.pid, body.resource, body.amount)


@app.post("/resources/avoidance-mode")
def set_avoidance_mode(body: AvoidanceModeRequest) -> dict[str, Any]:
    resource_manager.avoidance_mode = body.enabled
    return {"avoidance_mode": resource_manager.avoidance_mode}


# ---------------------------------------------------------------------------
# Detection + diagnosis + recovery
# ---------------------------------------------------------------------------


@app.post("/detect")
def detect() -> dict[str, Any]:
    processes = process_manager.list_processes()
    findings = run_detection(processes, resource_manager)

    results = []
    for finding in findings:
        pid = finding.get("pid")
        process = None
        if pid is not None:
            try:
                process = process_manager.get_process(pid)
            except ProcessNotFoundError:
                process = None

        error_id = database.log_error(pid, finding["error_type"], finding["details"])
        diag = diagnosis.diagnose(finding, process=process)
        database.log_diagnosis(error_id, diag["diagnosis_text"])
        action = recovery.run_recovery(finding, resource_manager)
        database.log_recovery_action(error_id, action["action_type"], action.get("target_pid"))

        results.append(
            {
                "error_id": error_id,
                "finding": finding,
                "diagnosis": diag,
                "recovery_action": action,
            }
        )

    return {"anomalies_found": len(results), "results": results}


# ---------------------------------------------------------------------------
# RAG assistant
# ---------------------------------------------------------------------------


@app.post("/ask")
def ask(body: AskRequest) -> dict[str, Any]:
    process = None
    if body.pid is not None:
        try:
            process = process_manager.get_process(body.pid)
        except ProcessNotFoundError:
            process = None
    return answer_question(body.question, process=process)


# ---------------------------------------------------------------------------
# Error log
# ---------------------------------------------------------------------------


@app.get("/errors")
def get_errors() -> list[dict[str, Any]]:
    return database.get_error_log()
