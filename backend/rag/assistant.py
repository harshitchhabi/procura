"""RAG assistant: retrieved knowledge-base chunks + live process context + question.

If GROQ_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY is set in the
environment, the assistant calls that LLM to generate a grounded answer.
Otherwise it falls back to a deterministic, clearly-labeled extractive
answer built directly from the retrieved chunks -- so the whole app works
fully offline with zero paid dependency, and the fallback is honest about
being extractive rather than pretending to be a generated answer.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from rag.retrieval import SearchResult, search

GROQ_MODEL = "openai/gpt-oss-20b"
ANTHROPIC_MODEL = "claude-3-5-haiku-20241022"
OPENAI_MODEL = "gpt-4o-mini"


def _format_process_context(process: Optional[dict[str, Any]]) -> str:
    if not process:
        return "No specific process was referenced."
    lines = [
        f"pid={process.get('pid')}",
        f"name={process.get('name')}",
        f"state={process.get('state')}",
        f"priority={process.get('priority')}",
        f"burst_time={process.get('burst_time')}",
        f"memory_requirement={process.get('memory_requirement')}",
        f"cpu_requirement={process.get('cpu_requirement')}",
        f"error_count={process.get('error_count')}",
        f"deadline={process.get('deadline')}",
    ]
    return "Process context: " + ", ".join(lines)


def _format_incident_facts(incident_facts: Optional[list[str]]) -> str:
    if not incident_facts:
        return "Incident facts: none recorded for this process."
    return "Incident facts (authoritative, from Procura's own logs):\n" + "\n".join(
        f"- {fact}" for fact in incident_facts
    )


def _build_prompt(
    question: str,
    chunks: list[SearchResult],
    process: Optional[dict[str, Any]],
    incident_facts: Optional[list[str]] = None,
) -> str:
    context_blocks = "\n\n".join(
        f"[Source: {r.chunk.source}]\n{r.chunk.text}" for r in chunks
    ) or "No relevant knowledge-base excerpts were found."
    return (
        "You are Procura's system assistant, an OS-concepts tutor embedded in a "
        "process-scheduling simulator. Answer the user's question using the "
        "knowledge-base excerpts and live process context below. Be concise, "
        "accurate, and explain the underlying OS concept clearly. Treat the "
        "incident facts as ground truth about what happened in this simulation: "
        "state causes and actions only as they appear there, and use the "
        "knowledge-base excerpts to explain the concept, not to invent extra "
        "causes (such as fragmentation) that the facts do not show.\n\n"
        f"{_format_process_context(process)}\n\n"
        f"{_format_incident_facts(incident_facts)}\n\n"
        f"Knowledge base excerpts:\n{context_blocks}\n\n"
        f"Question: {question}\n\nAnswer:"
    )


def _call_groq(prompt: str, api_key: str) -> Optional[str]:
    try:
        import httpx

        resp = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 600,
                "reasoning_effort": "low",
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content.strip() or None
    except Exception:
        return None


def _call_anthropic(prompt: str, api_key: str) -> Optional[str]:
    try:
        import httpx

        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return "".join(block.get("text", "") for block in data.get("content", []))
    except Exception:
        return None


def _call_openai(prompt: str, api_key: str) -> Optional[str]:
    try:
        import httpx

        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
            json={
                "model": OPENAI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500,
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def _extractive_fallback(
    question: str,
    chunks: list[SearchResult],
    process: Optional[dict[str, Any]],
    incident_facts: Optional[list[str]] = None,
) -> str:
    if not chunks:
        return (
            "[OFFLINE MODE - extractive answer]\n"
            "No closely-matching knowledge-base content was found for this question. "
            "Try rephrasing, or ask about CPU scheduling, memory management, deadlocks, "
            "process management, file systems, or error recovery."
        )

    lines = [
        "[OFFLINE MODE - extractive answer, no LLM API key configured]",
        f"Here are the most relevant knowledge-base passages for: \"{question}\"",
        "",
    ]
    for i, result in enumerate(chunks, start=1):
        snippet = result.chunk.text.strip()
        if len(snippet) > 400:
            snippet = snippet[:400].rsplit(" ", 1)[0] + "..."
        lines.append(f"{i}. (from {result.chunk.source}, relevance {result.score:.2f})\n   {snippet}")
    if process:
        lines.append("")
        lines.append(_format_process_context(process))
    if incident_facts:
        lines.append("")
        lines.append(_format_incident_facts(incident_facts))
    lines.append("")
    lines.append(
        "To get a fully generated, conversational answer instead of these excerpts, "
        "set GROQ_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY in backend/.env."
    )
    return "\n".join(lines)


def answer_question(
    question: str,
    process: Optional[dict[str, Any]] = None,
    top_k: int = 3,
    source_filter: list[str] | None = None,
    incident_facts: list[str] | None = None,
) -> dict[str, Any]:
    chunks = search(question, top_k=top_k, source_filter=source_filter)
    sources = [{"source": r.chunk.source, "score": round(r.score, 3), "excerpt": r.chunk.text[:200]} for r in chunks]

    groq_key = os.getenv("GROQ_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    prompt = _build_prompt(question, chunks, process, incident_facts)
    generated: Optional[str] = None
    mode = "offline_extractive"
    if groq_key:
        generated = _call_groq(prompt, groq_key)
        if generated:
            mode = "groq"
    if generated is None and anthropic_key:
        generated = _call_anthropic(prompt, anthropic_key)
        if generated:
            mode = "anthropic"
    if generated is None and openai_key:
        generated = _call_openai(prompt, openai_key)
        if generated:
            mode = "openai"

    answer = generated if generated else _extractive_fallback(question, chunks, process, incident_facts)
    return {"answer": answer, "mode": mode, "sources": sources}
