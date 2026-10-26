"""Re-grade saved answers in rag/results/grounding.json with the current checks (no model calls)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag.eval_grounding import QUESTIONS, grade

path = Path(__file__).resolve().parent / "results" / "grounding.json"
data = json.loads(path.read_text(encoding="utf-8"))
spec = {q[0]: q for q in QUESTIONS}
for r in data["results"]:
    _, _, _, _, must, must_not = spec[r["id"]]
    graded = [grade(a, must, must_not) for a in r["answers"]]
    r["passes"], r["failures"] = sum(ok for ok, _ in graded), sorted({f for _, why in graded for f in why})
    print(f"{r['id']:14} {'with facts   ' if r['grounded'] else 'facts removed'} {r['passes']}/{len(r['answers'])}  {r['failures'] or ''}")
path.write_text(json.dumps(data, indent=1), encoding="utf-8")
