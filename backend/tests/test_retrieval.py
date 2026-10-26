import pytest

from rag.retrieval import search


@pytest.mark.parametrize(
    "query, expected_source",
    [
        ("How is EEVDF different from Round Robin?", "Advanced_Scheduling"),
        ("What are the rules of the multi-level feedback queue MLFQ?", "Advanced_Scheduling"),
        ("What is Jain's fairness index?", "Advanced_Scheduling"),
        ("Why use a modified z-score instead of a fixed threshold?", "Anomaly_Detection"),
        ("How does CUSUM detect a shift?", "Anomaly_Detection"),
        ("Why is Banker's algorithm not used in practice, and what is wound-wait?", "Deadlocks"),
        # Memory_Management also answers this: it describes suspending the lowest-priority holder under memory pressure.
        ("When does recovery suspend a lower-priority process?", ("Error_Recovery", "Memory_Management")),
    ],
)
def test_knowledge_base_covers_procura_concepts(query, expected_source):
    results = search(query, top_k=3)
    assert results, "retrieval returned nothing"
    expected = {expected_source} if isinstance(expected_source, str) else set(expected_source)
    assert results[0].chunk.source in expected


from rag.eval_retrieval import HELD_OUT, QUERIES, evaluate
from rag.ingestion import tokenize_v1, tokenize_v2


def test_v2_tokenizer_keeps_numbers_and_identifiers():
    toks = tokenize_v2("EEVDF replaced CFS in kernel 6.6 and weight 1.25 and innodb_lock_wait_timeout")
    assert "6.6" in toks and "1.25" in toks
    assert "innodb_lock_wait_timeout" in toks and "timeout" in toks
    assert "6.6" not in tokenize_v1("kernel 6.6")


def test_v2_tokenizer_merges_simple_inflections_only():
    assert tokenize_v2("processes") == tokenize_v2("process") == ["process"]
    assert tokenize_v2("schedulers") == ["scheduler"]
    assert tokenize_v2("policies") == ["policy"]
    assert tokenize_v2("bus")[0] != tokenize_v2("business")[0]
    assert tokenize_v2("class") == ["class"]


def test_v2_tokenizer_splits_compounds_and_drops_question_filler():
    toks = tokenize_v2("Why does render-video fail?")
    assert "render-video" in toks and "render" in toks and "video" in toks
    assert "why" not in toks and "does" not in toks


def test_retrieval_accuracy_does_not_regress():
    dev = evaluate(tokenize_v2, QUERIES)
    held = evaluate(tokenize_v2, HELD_OUT)
    assert dev["top3"] >= 0.95 and dev["top1"] >= 0.85
    assert held["top3"] >= 0.95 and held["top1"] >= 0.85
