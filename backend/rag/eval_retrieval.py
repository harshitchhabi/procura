"""Retrieval evaluation: does the search return the right knowledge-base document?

A labelled set of questions, each with the document(s) that actually answer it.
Labels were written from the content of the knowledge base before any tokenizer
change was measured, and are not edited to suit a result.

Metrics, at document level (a hit means the retrieved chunk comes from an
acceptable document):
  top-1   the best-ranked chunk is from an acceptable document
  top-3   at least one of the three chunks the assistant is given is
  MRR     mean reciprocal rank of the first acceptable chunk within the top 5

Usage (from backend/):
    python -m rag.eval_retrieval
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.ingestion import build_index, tokenize, tokenize_v1
from rag.retrieval import search

ADV, CPU, PROC, MEM, FS, DL, ER, AN = (
    "Advanced_Scheduling", "CPU_Scheduling", "Process_Management", "Memory_Management",
    "File_System", "Deadlocks", "Error_Recovery", "Anomaly_Detection",
)

# (question, acceptable source documents, kind)
QUERIES: list[tuple[str, set[str], str]] = [
    ("What is the convoy effect?", {CPU, ADV}, "concept"),
    ("How does Round Robin choose the time quantum?", {CPU}, "concept"),
    ("Which scheduling algorithm minimises average waiting time?", {CPU, ADV}, "concept"),
    ("How are processes scheduled on one CPU?", {CPU, ADV, PROC}, "inflection"),
    ("Is there a way to starve a low priority process?", {CPU, ADV}, "concept"),
    ("How does EEVDF decide which task runs next?", {ADV}, "concept"),
    ("What happened to the Completely Fair Scheduler?", {ADV}, "concept"),
    ("What rules does MLFQ follow?", {ADV}, "concept"),
    ("Why does MLFQ boost priorities periodically?", {ADV}, "concept"),
    ("What is the range of Jain's fairness index?", {ADV}, "concept"),
    ("How does Slurm penalise heavy users over time?", {ADV}, "concept"),
    ("How is scheduling fairness measured quantitatively?", {ADV}, "inflection"),
    ("What does aging do to a waiting task's priority?", {ADV}, "concept"),
    ("Which Linux kernel version introduced EEVDF?", {ADV}, "numeric"),
    ("What weight does nice value zero get?", {ADV}, "numeric"),
    ("What states can a process be in?", {PROC}, "concept"),
    ("What is stored in a process control block?", {PROC}, "concept"),
    ("What is a context switch?", {PROC, CPU}, "concept"),
    ("Why would a memory allocation fail when total free memory is large?", {MEM}, "concept"),
    ("What is the difference between first-fit and best-fit?", {MEM}, "concept"),
    ("How does fragmentation waste memory?", {MEM}, "inflection"),
    ("What are the four conditions needed for deadlock?", {DL}, "concept"),
    ("How is a circular wait detected?", {DL}, "concept"),
    ("Why is Banker's algorithm rarely used in practice?", {DL}, "concept"),
    ("What does wound-wait do?", {DL}, "concept"),
    ("What is lock ordering and what checks it?", {DL}, "concept"),
    ("When does PostgreSQL check for a deadlock?", {DL}, "concept"),
    ("What does innodb_lock_wait_timeout do?", {DL}, "numeric"),
    ("What is a runbook?", {ER}, "concept"),
    ("When does recovery suspend a lower-priority task?", {ER}, "concept"),
    ("Why should the AI only explain and not act?", {ER}, "concept"),
    ("How does EWMA flag an anomaly?", {AN}, "concept"),
    ("Why is the modified Z-score better than the plain Z-score?", {AN}, "concept"),
    ("What kind of change does CUSUM detect?", {AN}, "concept"),
    ("How does journaling protect a file system?", {FS}, "concept"),
    ("What does a directory store in a file system?", {FS}, "concept"),
]

# Held-out questions: written after the v2 tokenizer was designed, from the
# document contents only, and evaluated once. They were not used to tune
# anything. Reported separately from QUERIES above.
HELD_OUT: list[tuple[str, set[str], str]] = [
    ("What is the purpose of the ready queue?", {CPU, PROC}, "concept"),
    ("What is turnaround time?", {CPU}, "concept"),
    ("When does a process become blocked?", {PROC}, "concept"),
    ("What does the terminated state mean?", {PROC}, "concept"),
    ("What are the symptoms of external fragmentation?", {MEM, FS}, "concept"),
    ("How are file permissions protected?", {FS}, "concept"),
    ("What are file attributes?", {FS}, "concept"),
    ("Which Coffman condition does lock ordering break?", {DL}, "concept"),
    ("How does Spanner avoid deadlock cycles?", {DL}, "concept"),
    ("How does a timeout abort help with deadlocks?", {DL, ER}, "concept"),
    ("What does the hold and wait condition mean?", {DL}, "concept"),
    ("What does an audit trail record after recovery?", {ER}, "concept"),
    ("What is Kubernetes preemption?", {ER}, "concept"),
    ("What is a fixed threshold rule and why is it weak?", {AN}, "concept"),
    ("What is a virtual deadline?", {ADV}, "concept"),
    ("How often are all jobs moved back to the top queue?", {ADV}, "numeric"),
    ("What does shortest job first risk for long jobs?", {CPU, ADV}, "concept"),
    ("What is lag in a fair share scheduler?", {ADV}, "concept"),
    ("How do production monitoring tools detect anomalies?", {AN, ER}, "concept"),
    ("Why do wait times differ between scheduling policies?", {CPU, ADV}, "concept"),
]


def evaluate(tokenizer, queries=None) -> dict:
    queries = QUERIES if queries is None else queries
    index = build_index(tokenizer=tokenizer)
    top1 = top3 = 0
    rr = 0.0
    misses = []
    by_kind: dict[str, list[int]] = {}
    for question, accept, kind in queries:
        ranked = [r.chunk.source for r in search(question, top_k=5, index=index)]
        rank = next((i + 1 for i, src in enumerate(ranked) if src in accept), None)
        top1 += rank == 1
        top3 += rank is not None and rank <= 3
        rr += 1.0 / rank if rank else 0.0
        by_kind.setdefault(kind, []).append(int(rank == 1))
        if rank != 1:
            misses.append((question, sorted(accept), ranked[:3] or ["(nothing)"]))
    n = len(queries)
    return {
        "n": n, "top1": top1 / n, "top3": top3 / n, "mrr": rr / n,
        "by_kind": {k: (sum(v), len(v)) for k, v in by_kind.items()},
        "chunks": len(index.chunks), "vocab": len(index.idf), "misses": misses,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    versions = [("v1 (original)", tokenize_v1)]
    if tokenize is not tokenize_v1:
        versions.append(("v2 (current)", tokenize))
    for label, queries in (("development set", QUERIES), ("held-out set", HELD_OUT)):
        print(f"--- {label} ({len(queries)} questions)")
        for name, tok in versions:
            r = evaluate(tok, queries)
            print(f"{name:14} top-1 {r['top1']:.1%}  top-3 {r['top3']:.1%}  MRR {r['mrr']:.3f}")
            for q, accept, got in r["misses"]:
                print(f"    miss: {q!r} wanted {accept}, got {got}")


if __name__ == "__main__":
    main()
