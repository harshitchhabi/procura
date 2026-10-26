"""Does the assistant tell the truth about what happened? A labelled evaluation.

Builds the two demo incidents inside a throw-away database (the memory-failure
recovery scenario and the two-task deadlock), then asks the live assistant a
fixed set of questions. Every answer is checked automatically against
patterns that must appear (the logged facts) and patterns that must not
(known failure modes seen earlier: invented causes, wrong units, invented
expansions of EEVDF, a claim that an action was the only possible one).

Each question is asked several times, because the model's wording varies. The
incident questions are asked twice: with the incident facts (how Procura
works) and without them (an ablation), so the contribution of grounding is a
measured number, not an assertion.

This calls a real LLM, so it needs a provider key in backend/.env and is not
part of the pytest suite.

Usage (from backend/):
    python -m rag.eval_grounding            # 3 trials per question
    python -m rag.eval_grounding --trials 5
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database  # noqa: E402

database.DB_PATH = Path(tempfile.mkdtemp(prefix="procura_eval_")) / "eval.db"

import main  # noqa: E402  (imported after DB_PATH is redirected; also loads .env)
from fastapi.testclient import TestClient  # noqa: E402

from os_sim.resource_manager import ResourceManager  # noqa: E402
from rag.assistant import answer_question  # noqa: E402
from seed_data import seed  # noqa: E402

UNIT_MISUSE = r"\b(?:64|20)\s*(?:MB|KB|GB|bytes?)\b"  # file handles / DB connections are not measured in bytes
ONLY_OPTION = r"(?:no other (?:action|option|way|mechanism)|only (?:possible |viable )?(?:way|option|action|mechanism|choice))"

# (id, scenario, pid or None, question, must match all, must match none, grounded-only)
QUESTIONS = [
    ("mem-no-victim", "memory", 5, "Why did this task hit a memory allocation failure, and what did the system do about it?",
     [r"1[, ]?600", r"248", r"no[_ ]victim|left pending|not evict|nothing (?:was )?evicted|did not (?:suspend|evict)|no (?:lower|other)"],
     [r"fragment", ONLY_OPTION]),
    ("mem-suspend", "memory", 2, "What did the system do for this task, and why was that allowed?",
     [r"768", r"suspend", r"\b(?:pid ?3|p3|grocery)\b", r"lower"],
     [r"fragment"]),
    ("mem-retry", "memory", 4, "Why did this task's allocation succeed on retry?",
     [r"retr", r"free|releas|available"],
     [r"fragment"]),
    ("dl-victim", "deadlock", 3, "Why was this task terminated, and was that the right choice?",
     [r"\b(?:pid ?1|p1)\b", r"lowest", r"cycle|circular|deadlock", r"terminat"],
     [UNIT_MISUSE, ONLY_OPTION]),
    ("dl-survivor", "deadlock", 1, "What happened to this task after the deadlock was resolved?",
     [r"ready|resum", r"releas|freed|free"],
     [UNIT_MISUSE]),
    ("dl-resources", "deadlock", 1, "Which resources were involved in the deadlock, and how much of each?",
     [r"file", r"database", r"\b64\b", r"\b20\b"],
     [UNIT_MISUSE]),
    ("c-eevdf", "concept", None, "How is EEVDF different from Round Robin?",
     [r"weight", r"lag|eligib|virtual deadline"],
     [r"effective[- ]priority\s+earliest", r"earliest[- ]deadline[- ]first[- ]variant"]),
    ("c-mlfq", "concept", None, "How does MLFQ avoid starving long jobs?",
     [r"boost"],
     []),
    ("c-jain", "concept", None, "What is Jain's fairness index and what values can it take?",
     [r"fair"],
     [r"(?<![\d/])0\s*(?:to|–|-|and)\s*1\b(?!\s*/)"]),  # the common misstatement: range 0..1 instead of 1/n..1
    ("c-banker", "concept", None, "Why is Banker's algorithm rarely used in real systems?",
     [r"maximum|advance|declare|in advance|known"],
     []),
    ("c-modz", "concept", None, "What does the modified Z-score use instead of the mean?",
     [r"median", r"MAD|absolute deviation"],
     []),
]


def build_scenario(client: TestClient, kind: str) -> None:
    with contextlib.redirect_stdout(io.StringIO()):
        seed()
    main.resource_manager = ResourceManager()
    from recovery import detector

    detector.reset_history()
    post = lambda path, body: client.post(path, json=body)  # noqa: E731
    if kind == "memory":
        post("/resources/allocate", {"pid": 3, "resource": "memory", "amount": 1200})
        post("/resources/allocate", {"pid": 1, "resource": "memory", "amount": 600})
    else:
        post("/resources/allocate", {"pid": 1, "resource": "file", "amount": 64})
        post("/resources/allocate", {"pid": 3, "resource": "database", "amount": 20})
        for pid in (1, 3):
            client.patch(f"/processes/{pid}", json={"action": "start"})
            client.patch(f"/processes/{pid}", json={"action": "pause"})
        post("/resources/allocate", {"pid": 1, "resource": "database", "amount": 5})
        post("/resources/allocate", {"pid": 3, "resource": "file", "amount": 5})
    client.post("/detect")


def normalise(text: str) -> str:
    """Models write numbers with narrow no-break spaces and non-breaking hyphens
    ("pid 1", "dead‑lock"). Fold them to plain characters so a pattern
    for "pid 1" matches what a reader sees."""
    return re.sub(r"[    ]", " ", text).replace("‑", "-").replace("‐", "-")


def grade(answer: str, must: list[str], must_not: list[str]) -> tuple[bool, list[str]]:
    answer = normalise(answer)
    failures = [f"missing /{p}/" for p in must if not re.search(p, answer, re.I)]
    failures += [f"forbidden /{p}/" for p in must_not if re.search(p, answer, re.I)]
    return not failures, failures


def ask(client: TestClient, pid, question: str, grounded: bool) -> dict:
    if grounded:
        return client.post("/ask", json={"question": question, "pid": pid}).json()
    process = main.process_manager.get_process(pid) if pid else None
    return answer_question(question, process=process, incident_facts=None)


def main_cli() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--pause", type=float, default=6.0, help="seconds between calls (free tiers limit tokens per minute)")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "results" / "grounding.json"))
    args = ap.parse_args()

    results = []
    with TestClient(main.app) as client:
        for scenario in ("memory", "deadlock", "concept"):
            if scenario != "concept":
                build_scenario(client, scenario)
            for qid, sc, pid, question, must, must_not in QUESTIONS:
                if sc != scenario:
                    continue
                for grounded in ((True, False) if pid else (True,)):
                    passes, fails, unavailable, samples = 0, [], 0, []
                    for _ in range(args.trials):
                        out = ask(client, pid, question, grounded)
                        if out["mode"] == "offline_extractive":  # the model never answered, even after retries
                            unavailable += 1
                            fails.append(f"model unavailable ({out.get('fallback_reason', 'no key')})")
                            continue
                        ok, why = grade(out["answer"], must, must_not)
                        passes += ok
                        fails += why
                        samples.append(out["answer"])
                        time.sleep(args.pause)
                    answered = args.trials - unavailable
                    results.append({"id": qid, "scenario": sc, "grounded": grounded, "passes": passes, "trials": answered,
                                    "unavailable": unavailable, "failures": sorted(set(fails)), "answers": samples})
                    cond = "with facts   " if grounded else "facts removed"
                    print(f"{qid:14} {cond} {passes}/{answered}" + (f"   ({unavailable} unavailable)" if unavailable else "")
                          + (f"   {sorted(set(fails))}" if fails else ""), flush=True)

    def rate(rows):
        t = sum(r["trials"] for r in rows)
        return sum(r["passes"] for r in rows) / t if t else float("nan")

    inc = [r for r in results if r["scenario"] != "concept"]
    summary = {
        "incident_with_facts": rate([r for r in inc if r["grounded"]]),
        "incident_facts_removed": rate([r for r in inc if not r["grounded"]]),
        "concept": rate([r for r in results if r["scenario"] == "concept"]),
        "overall_with_facts": rate([r for r in results if r["grounded"]]),
        "trials_requested_per_question": args.trials,
        "unavailable_trials": sum(r["unavailable"] for r in results),
        "unit_misuse_with_facts": sum(any("MB|KB" in f for f in r["failures"]) for r in results if r["grounded"]),
    }
    print("\n" + json.dumps(summary, indent=1))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "results": results}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main_cli()
