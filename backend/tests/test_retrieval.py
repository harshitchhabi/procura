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
        ("When does recovery suspend a lower-priority process?", "Error_Recovery"),
    ],
)
def test_knowledge_base_covers_procura_concepts(query, expected_source):
    results = search(query, top_k=3)
    assert results, "retrieval returned nothing"
    assert results[0].chunk.source == expected_source
