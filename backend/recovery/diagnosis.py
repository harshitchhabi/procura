"""Classifies detected failures and produces a plain-language diagnosis via the RAG assistant."""

from __future__ import annotations

from typing import Any, Optional

from rag.assistant import answer_question

SOURCE_MAP = {
    "burst_anomaly": ["CPU_Scheduling", "Error_Recovery"],
    "memory_failure": ["Memory_Management", "Error_Recovery"],
    "deadlock": ["Deadlocks", "Error_Recovery"],
    "timeout": ["CPU_Scheduling", "Error_Recovery"],
    "crash": ["Process_Management", "Error_Recovery"],
}

QUESTION_MAP = {
    "burst_anomaly": "Why would a process run much longer than its declared burst time, and what does that indicate?",
    "memory_failure": "What causes a memory allocation failure and how should an OS respond to it?",
    "deadlock": "What is a circular-wait deadlock and how is it detected and resolved?",
    "timeout": "What does it mean for a process to time out during scheduling, and how should it be handled?",
    "crash": "What are common causes of a process crash and how should an OS recover from it?",
}


def diagnose(finding: dict[str, Any], process: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Classify the failure type (already tagged by the detector) and ask the
    RAG assistant, grounded in the relevant knowledge-base file(s) and the
    live process/error data, for a plain-language diagnosis."""
    error_type = finding.get("error_type", "unknown")
    question = QUESTION_MAP.get(error_type, "What happened and how serious is this failure?")
    sources = SOURCE_MAP.get(error_type)

    contextual_question = (
        f"{question} Specific incident: {finding.get('details', 'no details available')}"
    )

    rag_result = answer_question(
        contextual_question,
        process=process,
        source_filter=sources,
        incident_facts=[f"{error_type}: {finding.get('details', 'no details available')}"],
    )
    return {
        "error_type": error_type,
        "diagnosis_text": rag_result["answer"],
        "mode": rag_result["mode"],
        "sources": rag_result["sources"],
    }
