# Procura

**Task management, reimagined as an OS process scheduler.** Procura is a local-first, single-user desktop-style web app that treats your to-do list as a set of OS processes: every task gets a PID, moves through a real process-state machine (NEW → READY → RUNNING → BLOCKED/COMPLETED/TERMINATED), and competes for simulated CPU, memory, file, database, and network resources. On top of the simulation sits a lightweight, fully-offline RAG layer that explains OS concepts grounded in a real knowledge base, plus an automated error-detection/diagnosis/recovery engine that behaves like a miniature self-healing OS. A companion terminal dashboard (`procura_top`, built with `rich`) lets you watch the same live data as an `htop`-style process monitor instead of a browser tab.

No authentication, no Docker, no cloud services, no background job queue -- everything runs synchronously on `localhost`, by design, so it installs and runs in seconds.

## Quickstart

### 1. Backend (FastAPI)

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env        # optional: add GROQ_API_KEY (free, checked first), ANTHROPIC_API_KEY, or OPENAI_API_KEY for live LLM answers
python seed_data.py         # populates ~6 demo tasks (one will trigger a memory_failure on /detect)
uvicorn main:app --reload
```

The API is now live at `http://localhost:8000` (interactive docs at `http://localhost:8000/docs`).

### 2. Frontend (React + Vite + Tailwind)

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The frontend talks to the backend at `http://localhost:8000` (CORS is pre-configured).

**Port 8000 already in use?** Run the backend on another port and point the frontend and terminal dashboard at it:

```bash
uvicorn main:app --port 8010                       # backend
VITE_API_URL=http://localhost:8010 npm run dev     # frontend
PROCURA_API_URL=http://localhost:8010 python -m cli.procura_top
```

(On Windows PowerShell, set the variable first: `$env:VITE_API_URL="http://localhost:8010"; npm run dev`.)

### 3. Terminal dashboard (the differentiator)

With the backend running, in a separate terminal:

```bash
cd backend
python -m cli.procura_top
```

This renders a live, polling `htop`-style dashboard: a color-coded process table, resource utilization bars, and a scrolling "AI SYSTEM" feed of diagnosis/recovery events -- the same live simulation data as the web dashboard, viewed as a literal terminal process monitor.

### 3b. Demo: create a deadlock and watch Procura resolve it

With a freshly seeded backend (`python seed_data.py`), build a circular wait between two tasks: each takes a whole pool, then asks for what the other holds.

```bash
A=http://localhost:8000; J="Content-Type: application/json"
curl -X POST $A/resources/allocate -H "$J" -d '{"pid":1,"resource":"file","amount":64}'
curl -X POST $A/resources/allocate -H "$J" -d '{"pid":3,"resource":"database","amount":20}'
curl -X POST $A/resources/allocate -H "$J" -d '{"pid":1,"resource":"database","amount":5}'   # fails: P1 now waits for P3
curl -X POST $A/resources/allocate -H "$J" -d '{"pid":3,"resource":"file","amount":5}'       # fails: P3 now waits for P1
curl $A/resources                                                                            # waiting_for_graph: {1:[3], 3:[1]}
curl -X POST $A/detect                                                                       # detect -> AI diagnosis -> recovery
```

`/detect` reports the cycle with who holds and waits for what, has the AI explain it, and applies the fixed deadlock rule: terminate the lowest-priority task in the cycle (P3), release its resources, and return the other (P1) to READY. Ask the assistant about P3 on the AI Assistant screen to see the explanation grounded in the logged cycle and the rule applied. (PowerShell users: use `Invoke-RestMethod` with `-ContentType "application/json"`, as in the demo script.)

### 4. Benchmarking

```bash
cd backend
python -m benchmark.run_benchmark                 # synthetic Poisson workload, all 6 algorithms
python -m benchmark.run_benchmark --swf benchmark/sample_traces/sample.swf   # replay a real-format SWF trace
```

Runs FCFS, SJF, Priority, Round Robin, EEVDF, and MLFQ against an identical workload and prints a comparison table (makespan, turnaround, waiting time, utilization, Jain's Fairness Index, starvation).

**Multi-seed statistical study.** One seeded run shows one workload. `python -m benchmark.study` runs every policy on 50 independent workloads (25 at n = 300) in three families (Gamma run times, heavy-tailed run times, bursty arrivals), at sizes 30 / 100 / 300 and a load sweep, and reports each metric as mean ± 95% confidence interval plus paired differences against FCFS. Results are saved to `backend/benchmark/results/study.json`.

Besides the textbook metrics it reports **bounded slowdown** and a second fairness index, **Jain's index over 1/slowdown** ("fairness of delay"). The classic index over total CPU received is identical for every work-conserving policy; the delay version is not, and separates them.

**Real traces.** The Parallel Workloads Archive blocks automated downloads, so no archive trace is bundled. Download one by hand (for example NASA-iPSC-1993-3.1-cln.swf), unzip it, and run `python -m benchmark.run_benchmark --swf path/to/file.swf`.

### 4b. Evaluating the assistant and the search

```bash
cd backend
python -m rag.eval_retrieval     # 36 development + 20 held-out questions, original vs current tokenizer
python -m rag.eval_grounding     # live model: 11 labelled questions x 3 trials, with and without the incident facts
python -m rag.regrade_grounding  # re-grade saved answers with the current checks, no model calls
```

`eval_grounding` calls a real model, so it needs a key in `backend/.env` and is not part of `pytest`. Free tiers limit tokens per minute; Procura retries rate-limited calls using the provider's own "try again in N seconds" hint, and reports `fallback_reason` (for example `groq: rate_limited`) when a configured model could not answer, instead of silently serving the offline answer as if no key were set. See [`PAPER.md`](./PAPER.md) for a full write-up with real measured results and citations back to the research underlying these upgrades.

### 5. Tests

```bash
cd backend
pytest tests/ -v
```

102 tests cover the scheduler algorithms (FCFS/SJF/Priority/Round Robin against hand-worked textbook examples, plus EEVDF/MLFQ shape/sanity checks and Jain's Fairness Index), process state-machine validation, resource allocation/over-capacity rejection, deadlock cycle detection (both a true circular-wait case and a non-circular negative case), the lock-ordering violation checker and timeout-based abort, the EWMA/Modified-Z-score/CUSUM statistical anomaly detectors, the recovery engine's preemption rules (never evict higher-priority work, only evict when it actually frees enough, retry when memory has already been freed), grounding of AI answers in recorded incident facts, knowledge-base retrieval for every concept Procura implements (EEVDF, MLFQ, Jain's index, fair-share, EWMA/CUSUM, lock ordering, preemption rules), the benchmark module's SWF parser and metric functions, and FastAPI `TestClient` smoke tests. Tests never call a live LLM, even if your `.env` has a key.

Screenshots of every screen, captured from the running system, are in [`docs/screenshots/`](./docs/screenshots/).

## Project structure

```
procura/
├── backend/            FastAPI app, os_sim (scheduler/process/resource managers),
│                        rag (offline TF-IDF retrieval + assistant), recovery
│                        (detector/diagnosis/recovery), benchmark (synthetic/SWF
│                        workloads + standard metrics + run_benchmark), cli
│                        (procura_top), tests
├── knowledge_base/     6 real, substantive OS-concepts reference documents
│                        (the RAG system's source material)
├── PAPER.md            Journal-style technical report: related work, system
│                        design, benchmarking methodology, and real measured
│                        results comparing all 6 scheduling algorithms
└── frontend/           React + Vite + Tailwind + Recharts, dark "process monitor" UI
```

## Feature-to-OS-concept map (for portfolio / viva use)

- **Process lifecycle & PCB (`os_sim/states.py`, `os_sim/process_manager.py`)** -- every task is a process with a strict, enforced state machine (NEW/READY/RUNNING/BLOCKED/COMPLETED/TERMINATED), mirroring the textbook process lifecycle and demonstrating why invalid transitions must be rejected to keep scheduler state consistent.
- **CPU scheduling (`os_sim/scheduler.py`)** -- FCFS, SJF, Priority (with a documented multi-factor effective-priority score: user priority + deadline urgency + waiting-time aging + resource weight + a Slurm-style decaying fair-share penalty), Round Robin, **EEVDF** (Linux's actual scheduler since kernel 6.6, implemented via per-process weight/vruntime/eligibility and a `heapq`-based earliest-virtual-deadline dispatch), and **MLFQ** (OSTEP's canonical multi-level feedback queue with cumulative per-level allotment accounting and periodic priority boost) -- six algorithms total, each producing real completion/turnaround/waiting/response-time metrics, Gantt-chart data, and a **Jain's Fairness Index** on every run, demonstrating the throughput-vs-fairness-vs-responsiveness tradeoffs between algorithms quantitatively, not just impressionistically.
- **Resource management & deadlock avoidance (`os_sim/resource_manager.py`)** -- five simulated resource pools (CPU/memory/file/database/network) with allocate/release, a waits-for graph, the original Banker's-algorithm-lite safety check (kept, but explicitly documented as the textbook baseline that production systems don't actually use), plus two production-grade mechanisms added alongside it: a **lockdep-style lock-ordering violation checker** (canonical resource-acquisition order, violations logged not blocked) and **timeout-based wait abort** (MySQL `innodb_lock_wait_timeout`-style).
- **Deadlock detection (`os_sim/resource_manager.py::detect_cycle`, `recovery/detector.py`)** -- proper DFS-based cycle detection over the waits-for graph (not just pairwise checks), demonstrating the formal graph-theoretic definition of circular wait, framed as the expensive-but-precise tier of a cost/precision spectrum alongside lock-ordering and timeout-based abort.
- **Statistical anomaly detection (`recovery/detector.py`)** -- EWMA, Modified Z-score, and CUSUM (all three NIST-SEMATECH-specified formulas), replacing/supplementing the original fixed-threshold "1.5x burst time" rule with a rolling-baseline statistical approach, selectable per detection call.
- **Benchmarking (`backend/benchmark/`)** -- a synthetic Poisson-arrival/Gamma-burst workload generator, a Standard Workload Format (SWF) trace parser, and `run_benchmark.py`, which replays an identical workload through all six scheduling algorithms and reports makespan/turnaround/waiting/utilization/fairness/starvation. See [`PAPER.md`](./PAPER.md) for full methodology and real results.
- **Offline-first RAG assistant (`rag/`)** -- a hand-rolled TF-IDF + cosine-similarity retriever (zero heavy ML dependencies) over real OS-concept documents, with an optional live-LLM path if an API key is set and a clearly-labeled deterministic extractive fallback otherwise, demonstrating retrieval-augmented, grounded (non-hallucinated) explanation.
- **Automated error recovery (`recovery/`)** -- detection (burst-time anomaly, memory failure, deadlock) → diagnosis (RAG-grounded plain-language explanation) → rule-based recovery script (suspend-and-retry, stop-and-retry, restart, terminate-and-resume), fully logged to SQLite, demonstrating how a real OS treats failure as a normal, recoverable condition rather than an exception to propagate.
- **`procura_top` terminal dashboard (`cli/procura_top.py`)** -- a `rich`-based live TUI polling the same REST API as the web frontend, demonstrating that the underlying simulation is a real backend service, not something coupled to a single UI.

## Notes on design choices

- **RAG is intentionally TF-IDF, not embeddings.** `rag/ingestion.py` explains why: no `sentence-transformers`/`faiss`/`chromadb`/`torch` dependency means `pip install` finishes in seconds and the whole app works fully offline with zero API keys. `retrieval.py`'s interface (`search(query, top_k) -> results`) is decoupled enough that a real embedding-based index could be swapped in later without touching any calling code.
- **SQLite via raw `sqlite3`, no ORM** (`backend/database.py`) -- every query is visible and easy to audit, appropriate for this project's scope.
- **In-memory resource manager** -- the `ResourceManager` singleton in `main.py` lives for the lifetime of the running `uvicorn` process; process/error/diagnosis/recovery history is persisted to SQLite, but live resource allocations reset on restart (by design, since this is a live simulation, not a durable ledger).
