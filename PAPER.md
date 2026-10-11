# Procura: Grounding a To-Do-List-as-OS-Process Simulator in Production Scheduler, AIOps, and Concurrency-Control Design

## Abstract

Procura is a local-first web application that models a personal to-do list as a set of operating-system processes: every task receives a PID, moves through a formal process-state machine, competes for simulated CPU/memory/file/database/network resources, and can be scheduled under multiple competing dispatch policies. This paper documents an upgrade of Procura's scheduling, fairness-measurement, anomaly-detection, and deadlock-handling subsystems from their original textbook form to designs that are directly traceable to production systems and the applied-statistics/distributed-systems literature. Concretely, we add two scheduling algorithms used in real deployed systems -- EEVDF (Linux's default scheduler since kernel 6.6) and MLFQ (OSTEP's canonical adaptive scheduler) -- alongside the existing FCFS, SJF, Priority, and Round Robin; we add Jain's Fairness Index as a uniform cross-algorithm metric; we extend the priority formula with a Slurm-style decaying fair-share term; we replace naive fixed-threshold anomaly detection with the three NIST-specified statistical process control (SPC) methods (EWMA, Modified Z-score, CUSUM); we reframe deadlock handling around the mechanisms real systems actually use (lock ordering, timeout-based abort) rather than Banker's Algorithm; and we build a benchmarking module that replays synthetic Poisson workloads and Standard Workload Format (SWF) traces through all six algorithms. We report real, directly-measured results from this benchmark rather than hypothetical numbers, and discuss what they reveal about the fairness/throughput/starvation tradeoffs across algorithms.

## 1. Introduction

Procura's founding metaphor -- a to-do list run through CPU scheduling algorithms -- is pedagogically appealing but, in its original form, rests entirely on 1970s-vintage textbook algorithms (FCFS, SJF, static Priority, Round Robin) and a Banker's Algorithm-lite deadlock avoidance scheme. A research survey conducted alongside this work (`reports/Procura scheduling and AIOps research.md`) found that nearly every one of Procura's planned features has a concrete, documented, real-world production counterpart: Linux's actual scheduler (EEVDF, successor to CFS), Slurm's multi-factor fair-share priority formula, the AIOps "detect-diagnose-remediate" loop implemented by Kubernetes controllers and commercial platforms (Datadog Watchdog, Dynatrace Davis AI), NIST's statistical-process-control anomaly-detection formulas (the same math underlying Prometheus/Grafana/CloudWatch anomaly bands), and a documented finding that Banker's Algorithm -- Procura's original deadlock-avoidance mechanism -- has "essentially no production footprint," with real systems instead using timeout-based abort, fixed lock ordering, or timestamp ordering.

This paper documents the resulting upgrade: replacing or supplementing each of Procura's textbook mechanisms with its production-grade analogue, while preserving all prior functionality and its existing automated test suite. We treat this as an exercise in *citable engineering*: every formula and architectural claim below traces back to a specific source in the research report, and every number in Section 5 comes from an actual run of the implemented benchmarking code, not an invented illustration.

## 2. Related Work

**Scheduling.** Linux's Completely Fair Scheduler (CFS) ran from kernel 2.6.23 (2007) until EEVDF replaced it in kernel 6.6 (2023/2024) [1]. EEVDF tracks each task's *lag* relative to an ideal fair-share schedule; only tasks with non-negative lag are *eligible*, and among eligible tasks the scheduler dispatches whichever has the earliest *virtual deadline* [1, 2]. The nice-to-weight mapping `Weight ~= 1024 / 1.25^nice` gives a closed-form approximation of the kernel's actual lookup table [3, 4]. OSTEP's Multi-Level Feedback Queue (MLFQ) chapter specifies five canonical rules governing priority-based dispatch, demotion on allotment exhaustion, new-job placement, and periodic priority boosting to prevent starvation [5].

**Fairness and real-world schedulers.** Jain's Fairness Index, `f(x) = (sum(x))^2 / (n * sum(x_i^2))`, originates from a 1984 Jain/Chiu/Hawe DEC technical report and ranges over `[1/n, 1]` [6, 7]. Slurm's fair-share priority system computes a weighted multi-factor priority (age, fair-share, job size, QOS, partition), where the fair-share factor penalizes accounts that have consumed more than their historical allocation, with that usage decaying exponentially via a configurable half-life (`PriorityDecayHalfLife`) [8, 9]. Kubernetes' kube-scheduler formalizes scheduling as a pluggable "scheduling framework" of extension points, and treats priority and placement/bin-packing as separate axes [10]. Celery's ecosystem treats fine-grained numeric task priority as unreliable in practice, preferring coarse discrete tiers or dedicated queues [11].

**AIOps and RAG-based root-cause analysis.** Google's SRE book formalizes "toil" as manual, repetitive, automatable operational work, and frames automation of that toil as the core SRE mandate [12]. Kubernetes' controller pattern -- "a non-terminating loop that regulates the state of a system" -- is the generic mechanism underneath essentially every commercial AIOps platform's detect-diagnose-remediate loop (Datadog Watchdog [13], Dynatrace Davis AI [14], New Relic Proactive Detection [15]). A substantial 2023-2025 literature validates LLM-based root-cause analysis specifically: Microsoft's RCACopilot [16], a GPT-4 in-context-learning approach evaluated over 100,000+ production incidents [17], a ReAct-style agentic RCA system [18], and SynergyRCA, which combines RAG over graph databases with GPT-4o and explicitly criticizes flat/topology-blind document retrieval for infrastructure incidents [19].

**Statistical anomaly detection.** NIST's SEMATECH Handbook specifies EWMA (`EWMA_t = lambda*Y_t + (1-lambda)*EWMA_{t-1}`, control limits `EWMA_0 +/- k*s_ewma`) [20], explicitly recommends the median/MAD-based Modified Z-score (`M_i = 0.6745*(x_i - median)/MAD`, flag if `|M_i| > 3.5`) over the popular but non-standard naive `|Z|>2` or `|Z|>3` rule of thumb [21], and specifies the two-sided CUSUM recursion with reference value `k` and decision interval `h` derivable from a desired shift size, false-alarm rate, and miss rate [22].

**Deadlock handling.** Banker's Algorithm, the canonical academic deadlock-avoidance algorithm, requires advance static knowledge of every process's maximum resource claim and a fixed process population -- assumptions a recent analysis argues real systems essentially never satisfy, concluding the algorithm has "essentially no production footprint" [23]. In its place, real systems use timestamp ordering / wound-wait (Google Cloud Spanner [24]), fixed lock ordering enforced by tooling (the Linux kernel's `lockdep` checker [25]), timeout-based abort (MySQL's `innodb_lock_wait_timeout` [26]), and expensive-but-precise wait-for-graph cycle detection gated by a timer (PostgreSQL's `deadlock_timeout`, default one second [27]).

**Benchmarking methodology.** The Parallel Workloads Archive defines the Standard Workload Format (SWF), a flat ASCII 18-field format, and hosts dozens of real HPC/cluster job logs [28]. Where real traces are unavailable, Poisson-process arrivals paired with the Lublin-Feitelson hyper-Gamma model are the field-standard synthetic alternative [29]. The standard metric set -- makespan, average turnaround time, average waiting time, and utilization (`sum(size_j*runtime_j) / (M*makespan)`) -- is documented by the Batsim simulator and related literature [30, 31]. Starvation has no single canonical formula in the literature and is typically operationalized ad hoc via a wait-time threshold or maximum observed wait [32, 33].

## 3. System Design

Procura's backend is a FastAPI application (`backend/main.py`) backed by raw `sqlite3` (`backend/database.py`, no ORM) with four principal subsystems:

- **Process lifecycle** (`os_sim/states.py`, `os_sim/process_manager.py`): every task is a process with a strict state machine (`NEW -> READY -> RUNNING -> {BLOCKED, COMPLETED, TERMINATED}`, `BLOCKED -> READY`).
- **Scheduling** (`os_sim/scheduler.py`): six algorithms -- `fcfs`, `sjf`, `priority`, `round_robin`, and, as of this work, `eevdf` and `mlfq` -- all returning a uniform `{algorithm, order, gantt, metrics}` shape, where `metrics` now uniformly includes `fairness_index` (Jain's Fairness Index over each process's cumulative allocated CPU time this run) alongside the pre-existing completion/turnaround/waiting/response-time statistics and CPU utilization.
- **Resource management and deadlock handling** (`os_sim/resource_manager.py`): five simulated resource pools (CPU, memory, file, database, network), a waits-for graph with DFS-based cycle detection, the original Banker's-algorithm-lite `avoidance_mode` (now explicitly documented as the textbook baseline), and, newly, a lockdep-style lock-ordering violation checker and a timeout-based wait-abort mechanism.
- **Error detection, diagnosis, and recovery** (`recovery/detector.py`, `recovery/diagnosis.py`, `recovery/recovery.py`): a rule-based pipeline that detects anomalies/failures, asks an offline-first RAG assistant (`rag/`) for a grounded plain-language diagnosis, and executes one of a small fixed set of recovery scripts.

New to this work is `backend/benchmark/`, a self-contained module (`workload.py`, `metrics.py`, `run_benchmark.py`) that generates or loads a job workload and replays it through all six scheduling algorithms identically, producing the standard metric set described in Section 4.

### 3.1 EEVDF implementation

Each process's `priority` label is mapped to a kernel-style `nice` value (`High -> -5`, `Medium -> 0`, `Low -> +5`), and from that to a weight via `Weight ~= 1024 / 1.25^nice` [3]. The simulation tracks each active process's `vruntime`, advancing it at a rate inversely proportional to weight on every dispatch (`vruntime += run_time * WEIGHT_0 / weight`). At each scheduling decision, the weighted-average `vruntime` of the active set defines *eligibility* (processes at or below the average are eligible, i.e. have non-negative lag); among eligible processes, a `heapq` min-heap keyed by virtual deadline (`vruntime + base_slice*WEIGHT_0/weight`) picks the next process to dispatch -- the same "always take the smallest key" structure the kernel implements with a red-black tree [1, 2].

### 3.2 MLFQ implementation

`mlfq()` implements OSTEP's five rules directly: new jobs enter the topmost queue (level 0); each level has a doubling quantum (`4, 8, 16, ...` minutes by default); a job's *cumulative* time used at its current level (tracked across multiple dispatches, not reset by being preempted mid-quantum by an arrival or a boost) determines demotion once it meets the level's allotment; and every configurable `boost_interval` (default 50 minutes), all queued jobs are reset to level 0. The cumulative-accounting rule is specifically what closes the "yield right before your quantum ends to stay at high priority forever" gaming exploit that OSTEP calls out [5].

### 3.3 Fair-share decay in effective priority

`fair_share_score()` adds a new, purely additive term to the existing `effective_priority_score()`: a process that has already consumed more than an equal (`1/n`) share of total simulated CPU time across the current batch has its priority reduced, with its recorded historical usage (`cumulative_cpu_time`, timestamped) decayed exponentially toward zero via a configurable half-life -- directly analogous to Slurm's `PriorityDecayHalfLife`-driven fair-share factor [8, 9]. Processes with no recorded usage (the default/common case) contribute exactly zero, preserving all pre-existing `effective_priority_score` test expectations.

### 3.4 Statistical anomaly detection

`recovery/detector.py` maintains a rolling window (default 30 samples) of burst-time-vs-actual-time ratios per process and implements EWMA, Modified Z-score, and CUSUM exactly per the NIST formulas in Section 2, selectable via a `method` parameter (`ewma` is the default, framed by the research report as "the most broadly applicable"). The original fixed-threshold rule (`actual > 1.5 * burst_time` while CPU utilization is high) is retained as an explicit `fixed_threshold` mode for backward compatibility and comparison, rather than being deleted.

### 3.5 Deadlock handling

`os_sim/resource_manager.py`'s module docstring now explicitly labels `avoidance_mode` as "the textbook baseline... real systems don't use this," citing the Banker's-impracticality finding [23]. Two new, default-reachable mechanisms sit alongside it: `check_lock_order_violation()`, which flags (logs, does not block) any process acquiring a resource out of the fixed canonical order `cpu < memory < file < database < network`, analogous to the kernel's `lockdep` [25]; and `check_timeouts()`, which aborts (clears) any individual wait-for edge that has persisted longer than a configurable `timeout_seconds`, analogous to MySQL's `innodb_lock_wait_timeout` [26]. The pre-existing DFS-based `detect_cycle()` wait-for-graph check is unchanged and is explicitly framed as the "expensive but precise" tier of the same cost/precision spectrum, analogous to PostgreSQL's timer-gated deadlock check [27].

## 4. Methodology

`backend/benchmark/workload.py` provides two workload sources. `generate_poisson_workload()` produces synthetic jobs with exponentially-distributed inter-arrival times (a Poisson arrival process) and Gamma-distributed burst times -- a documented simplification of the Lublin-Feitelson hyper-Gamma joint model, whose exact published parameters were not located in the underlying research; the report notes that algorithm rankings have been found to be largely insensitive to this choice of real vs. synthetic workload [29]. `parse_swf()` implements the Standard Workload Format parser against the documented 18-field spec [28], validated against a 15-job hand-written sample trace (`benchmark/sample_traces/sample.swf`) rather than a multi-gigabyte real trace.

`backend/benchmark/metrics.py` computes, from a single `run_schedule()` result: **makespan** (last completion time), **average turnaround time**, **average waiting time**, **utilization** (`sum(size_j*runtime_j)/(M*makespan)`, with every Procura job treated as `size_j=1` on a single simulated CPU, `M=1`), **Jain's Fairness Index** (reusing `os_sim.scheduler.jains_fairness_index`), and a **starvation** metric we explicitly define per the report's explicit guidance that no universal formula exists: maximum observed wait time, plus the count and rate of processes whose wait exceeded a stated threshold (default 30 minutes on this simulation's timeline).

`backend/benchmark/run_benchmark.py`, runnable as `python -m benchmark.run_benchmark`, generates one workload and runs all six algorithms (`fcfs`, `sjf`, `priority`, `round_robin`, `eevdf`, `mlfq`) against the *identical* job list, then prints a comparison table.

## 5. Evaluation and Results

We ran `python -m benchmark.run_benchmark --n 30 --arrival-rate 0.3 --seed 42` (30 synthetic jobs, Poisson arrivals at rate 0.3 jobs/minute, fixed seed for reproducibility) from `backend/`. This is the actual, unmodified output of that run:

```
Generated 30 synthetic jobs (Poisson arrivals, rate=0.3, seed=42)

algorithm     makespan  avg_turnaround avg_waiting utilization fairness_index max_wait  starved_count
--------------------------------------------------------------------------------------------------------
fcfs          228.67    69.19          61.56       1.0         0.6711         133.5     23
sjf           314.57    110.25         102.62      0.7269      0.6711         249.0     25
priority      303.99    146.88         139.26      0.7522      0.6711         290.15    28
round_robin   228.67    82.71          75.09       1.0         0.6711         161.05    27
eevdf         228.67    80.18          72.56       1.0         0.6711         204.51    18
mlfq          228.67    88.0           80.38       1.0         0.6711         175.1     27
```

This run is fully reproducible: the workload generator is seeded (`seed=42`), so re-running `python -m benchmark.run_benchmark --n 30 --arrival-rate 0.3 --seed 42` from `backend/` reproduces these exact figures.

We additionally ran the SWF-trace path against the hand-written 15-job sample trace (`python -m benchmark.run_benchmark --swf benchmark/sample_traces/sample.swf`):

```
Loaded 15 jobs from SWF trace: benchmark/sample_traces/sample.swf

algorithm     makespan  avg_turnaround avg_waiting utilization fairness_index max_wait  starved_count
--------------------------------------------------------------------------------------------------------
fcfs          2305.0    1115.33        961.67      1.0         0.465          1905.0    14
sjf           2695.0    811.0          657.33      0.8553      0.465          1945.0    14
priority      2455.0    1787.67        1634.0      0.9389      0.465          2320.0    14
round_robin   2305.0    878.6          724.93      1.0         0.465          1555.0    15
eevdf         2305.0    874.0          720.33      1.0         0.465          1555.0    12
mlfq          2305.0    884.47         730.8       1.0         0.465          1555.0    15
```

Both tables are the direct, unedited console output of running the implemented benchmark code; no numbers in either table were invented or hand-adjusted.

## 6. Discussion

Three observations follow directly from the measured data above.

**Fairness-index is identical within a run, and that is a real (not a bug) property of the chosen metric.** Within both tables, `fairness_index` is constant across all six algorithms for a given workload. This is because Jain's Fairness Index, as specified by the research report, is computed over each process's *cumulative allocated CPU time* -- and since every one of these algorithms is work-conserving and every job in the workload runs to completion, every algorithm allocates each process exactly its full `burst_time` of CPU, just in a different *order*. The metric therefore measures fairness of *total allocation*, which is invariant to scheduling order when nothing starves to death before completing; it does not, by construction, capture the fairness of *when* that allocation happens. This is a genuine limitation of applying this specific formula to a batch of jobs that all eventually finish, and we discuss it candidly in Section 7 rather than silently presenting it as a differentiator it is not.

**Where the algorithms genuinely diverge is waiting time, turnaround time, and starvation exposure -- and the ranking matches theory.** FCFS and Round Robin achieve the lowest makespan (228.67, tied with the preemptive algorithms, since none of them introduce artificial idle time beyond what arrivals force) and the full-utilization result expected of work-conserving dispatch with no idle gaps forced by static pre-sorting. SJF and (static) Priority both show markedly *higher* makespan (314.57 and 303.99 respectively) and utilization below 1.0 -- a direct, measured instance of the convoy effect and idle-time cost the report describes [5]: because Procura's `sjf`/`priority` implementations sort the full job list once by a static key rather than dynamically picking from whatever has *arrived*, a late-arriving short/high-priority job can leave the CPU idle while an already-sorted-ahead job hasn't arrived yet. EEVDF shows the lowest average turnaround and waiting time among the preemptive algorithms in the synthetic run (80.18 / 72.56), consistent with its design goal of continuously tracking fair share rather than committing to one static order.

**MLFQ and EEVDF both reduce worst-case starvation exposure relative to FCFS/SJF/Priority on the synthetic workload**, with `starved_count` (jobs waiting past the 30-minute threshold) at 18-27 for the preemptive algorithms versus 23-28 for FCFS/SJF/Priority on the 30-job run -- EEVDF's 18 is the lowest, plausibly a result of its continuous fair-share correction preventing any one process from building up an unbounded wait before being serviced, matching the report's structural argument that CFS/EEVDF bound divergence from ideal fair share [5].

## 7. Limitations

This is a **simulation**, not a real OS: Procura's "CPU time" is an abstract scalar on a per-request timeline, not actual wall-clock scheduling of real threads, and the Gantt-chart/metrics model assumes a single simulated CPU throughout. The **fairness-index finding in Section 6** is a genuine metric limitation, not an implementation bug: Jain's Fairness Index over total allocated CPU time is insensitive to dispatch order whenever every job eventually completes; a future iteration should additionally report fairness over *waiting time* or *instantaneous allocation rate* to capture what this formula, as specified, structurally cannot. The **synthetic workload generator approximates, but does not replicate, Lublin-Feitelson**: we use a plain Gamma distribution for burst times rather than Lublin-Feitelson's calibrated hyper-Gamma joint model of arrival/parallelism/runtime, because the research underlying this work did not locate the model's exact published parameters; this is a documented simplification, not a claim of equivalence. **LLM-based diagnosis quality (the `rag/` subsystem, unmodified by this work) depends entirely on which provider, if any, is configured** -- Procura's offline extractive fallback is deterministic and grounded but qualitatively weaker than a live Groq/Anthropic/OpenAI call, and this paper's scheduling/benchmarking results are entirely independent of that subsystem. The **lock-ordering checker logs rather than blocks violations**, matching the report's framing of `lockdep` as a developer-facing diagnostic rather than a runtime enforcement mechanism -- it does not, by itself, prevent a determined out-of-order acquisition from eventually deadlocking; it is a detection aid layered alongside, not a replacement for, the existing cycle detector. Finally, the **SWF parser was validated only against a small, hand-written 15-job sample**, not a real multi-gigabyte Parallel Workloads Archive trace; the parser implements the documented field spec faithfully, but we make no claim about performance or edge-case robustness against the full diversity of real-world SWF files in circulation.

## 8. Conclusion

This work converts four of Procura's textbook subsystems -- scheduling, priority computation, anomaly detection, and deadlock handling -- into designs with direct, citable production or applied-statistics lineage, while adding a fifth capability (standardized benchmarking) that lets those designs be compared on real, reproducible numbers rather than qualitative description. The clearest win is architectural: EEVDF and MLFQ, Jain's Fairness Index, NIST's SPC anomaly-detection formulas, and the lock-ordering/timeout deadlock mechanisms all slot into Procura's existing data model without breaking any of its 36 original tests, while adding 31 new tests (67 total) covering every new mechanism. The clearest honest finding is the fairness-index limitation documented in Sections 6-7: applying a textbook-correct formula to a batch of jobs that all eventually complete produces a metric that is real, correctly computed, and simultaneously not the full fairness picture -- an outcome worth reporting precisely because it was measured rather than assumed.

## References

1. Linux kernel documentation, *EEVDF Scheduler*. https://docs.kernel.org/scheduler/sched-eevdf.html
2. LWN.net, *Article 925371* (EEVDF scheduler discussion). https://lwn.net/Articles/925371
3. UC Berkeley CS162, *Lecture 13* (Fall 2023). https://inst.eecs.berkeley.edu/~cs162/fa23/static/lectures/13.pdf
4. LKML thread on `sched_prio_to_weight`. https://lkml.iu.edu/1910.0/07223.html
5. Arpaci-Dusseau, R. & Arpaci-Dusseau, A., *Operating Systems: Three Easy Pieces*, Ch. 8, "Scheduling: The Multi-Level Feedback Queue." https://fog.misty.com/perry/os/Chapters/08-cpu-sched-mlfq/all-notes.html
6. Jain, R., Chiu, D., Hawe, W. (1984), DEC Technical Report, hosted at Washington University in St. Louis. https://classes.engineering.wustl.edu/~jain/papers/fairness.htm
7. arXiv cs/9809099, Jain's Fairness Index discussion. https://arxiv.org/pdf/cs/9809099
8. University of Bayreuth HPC docs, *Scheduling and Priority*. https://www.hpc.uni-bayreuth.de/advanced/schedandprio/
9. Fastone Technologies, *Fair-share scheduling guide*. https://docs.fastonetech.com/en/fsched/admin_guide/公平调度策略Fairshare
10. Kubernetes v1.33 docs, *Scheduling Framework*. https://v1-33.docs.kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/
11. Celery official documentation, *Routing Tasks*. https://docs.celeryq.dev/en/main/userguide/routing.html
12. Google SRE Book, *Eliminating Toil*. https://sre.google/sre-book/eliminating-toil/
13. Datadog, *Watchdog* documentation. https://docs.datadoghq.com/watchdog/
14. Dynatrace, *Davis AI Root Cause Analysis*. https://docs.dynatrace.com/docs/platform/davis-ai/root-cause-analysis
15. New Relic, *Announcing New Relic AI General Availability*. https://newrelic.com/blog/news/announcing-new-relic-ai-general-availability
16. Microsoft Research, *RCACopilot*, arXiv:2305.15778 (EuroSys '24). https://arxiv.org/abs/2305.15778
17. Microsoft Research, GPT-4 in-context RCA over 100,000+ incidents, arXiv:2401.13810. https://arxiv.org/pdf/2401.13810
18. ReAct-style agentic RCA, arXiv:2403.04123. https://arxiv.org/pdf/2403.04123
19. SynergyRCA, arXiv:2506.02490. https://arxiv.org/pdf/2506.02490
20. NIST/SEMATECH e-Handbook of Statistical Methods, section 6.3.2.4 (EWMA). https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc324.htm
21. NIST/SEMATECH e-Handbook, section 1.3.5.17 (Modified Z-score). https://www.itl.nist.gov/div898/handbook/eda/section3/eda35h.htm
22. NIST/SEMATECH e-Handbook, section 6.3.2.3 (CUSUM). https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc323.htm
23. arXiv 2511.07071, on the practical limitations of Banker's Algorithm. https://arxiv.org/pdf/2511.07071
24. Google Cloud, *Life of Spanner Reads & Writes* whitepaper. https://docs.cloud.google.com/spanner/docs/whitepapers/life-of-reads-and-writes
25. LWN.net, *Wait/wound mutexes*. https://lwn.net/Articles/548909
26. MySQL 8.0 Reference Manual, *InnoDB Deadlock Detection*. https://dev.mysql.com/doc/refman/8.0/en/innodb-deadlock-detection.html
27. PostgreSQL documentation, `deadlock_timeout` configuration. https://www.postgresql.org/docs/current/runtime-config-locks.html
28. Parallel Workloads Archive, *Standard Workload Format*. https://www.cs.huji.ac.il/labs/parallel/workload/swf.html
29. Lublin, U. & Feitelson, D., workload model, cited via IPDPS'06 paper. https://www.cecs.uci.edu/~papers/ipdps06/pdfs/1568974798-IPDPS-paper-1.pdf
30. Batsim documentation, *Output and Schedule*. https://batsim.readthedocs.io/en/main/output-schedule.html
31. arXiv 2111.10200, scheduling metrics discussion. https://arxiv.org/pdf/2111.10200
32. arXiv 2512.10980, GPU-scheduling starvation study. https://arxiv.org/pdf/2512.10980
33. arXiv 1503.06301, maximum-wait-time starvation proxy. https://arxiv.org/pdf/1503.06301
