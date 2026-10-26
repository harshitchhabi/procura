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
import re
import time
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
        "causes (such as fragmentation) that the facts do not show. Use units "
        "exactly as written in the facts (file handles, database connections, "
        "MB of memory, % of CPU, Mbps) and never invent a unit. Do not call an "
        "action the only possible one unless the facts say so: real systems also "
        "have other options, such as preemption, retry or lock ordering.\n\n"
        f"{_format_process_context(process)}\n\n"
        f"{_format_incident_facts(incident_facts)}\n\n"
        f"Knowledge base excerpts:\n{context_blocks}\n\n"
        f"Question: {question}\n\nAnswer:"
    )


_RETRY_HINT = re.compile(r"try again in ([0-9.]+)\s*(ms|s)", re.I)


def _post_json(url: str, headers: dict[str, str], body: dict[str, Any], attempts: int = 3) -> tuple[Optional[dict], Optional[str]]:
    """POST and return (json, None), or (None, reason). Retries rate limits (429)
    and transient server errors, waiting as long as the provider asks (capped),
    so a busy minute on a free tier does not silently become an offline answer."""
    import httpx

    reason = "request_failed"
    for attempt in range(attempts):
        try:
            resp = httpx.post(url, headers=headers, json=body, timeout=45.0)
        except httpx.HTTPError:
            reason = "network_error"
            time.sleep(1.0 + attempt)
            continue
        if resp.status_code == 200:
            return resp.json(), None
        if resp.status_code == 429 or resp.status_code >= 500:
            reason = "rate_limited" if resp.status_code == 429 else "provider_error"
            wait = 0.0
            if resp.headers.get("retry-after"):
                try:
                    wait = float(resp.headers["retry-after"])
                except ValueError:
                    pass
            if not wait:
                m = _RETRY_HINT.search(resp.text)
                if m:
                    wait = float(m.group(1)) / (1000.0 if m.group(2).lower() == "ms" else 1.0) + 0.5
            time.sleep(min(max(wait, 1.0), 15.0))
            continue
        return None, f"http_{resp.status_code}"
    return None, reason


def _call_groq(prompt: str, api_key: str) -> tuple[Optional[str], Optional[str]]:
    # gpt-oss is a reasoning model: reasoning tokens count against max_tokens, so a
    # tight budget can leave the visible answer empty. 1500 leaves room for both.
    data, reason = _post_json(
        "https://api.groq.com/openai/v1/chat/completions",
        {"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
        {"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 1500, "reasoning_effort": "low"},
    )
    if data is None:
        return None, reason
    try:
        content = (data["choices"][0]["message"].get("content") or "").strip()
    except (KeyError, IndexError):
        return None, "bad_response"
    return (content, None) if content else (None, "empty_answer")


def _call_anthropic(prompt: str, api_key: str) -> tuple[Optional[str], Optional[str]]:
    data, reason = _post_json(
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        {"model": ANTHROPIC_MODEL, "max_tokens": 700, "messages": [{"role": "user", "content": prompt}]},
    )
    if data is None:
        return None, reason
    text = "".join(block.get("text", "") for block in data.get("content", [])).strip()
    return (text, None) if text else (None, "empty_answer")


def _call_openai(prompt: str, api_key: str) -> tuple[Optional[str], Optional[str]]:
    data, reason = _post_json(
        "https://api.openai.com/v1/chat/completions",
        {"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
        {"model": OPENAI_MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 700},
    )
    if data is None:
        return None, reason
    try:
        content = (data["choices"][0]["message"].get("content") or "").strip()
    except (KeyError, IndexError):
        return None, "bad_response"
    return (content, None) if content else (None, "empty_answer")


def _extractive_fallback(
    question: str,
    chunks: list[SearchResult],
    process: Optional[dict[str, Any]],
    incident_facts: Optional[list[str]] = None,
    fallback_reason: Optional[str] = None,
) -> str:
    if not chunks:
        return (
            "[OFFLINE MODE - extractive answer]\n"
            "No closely-matching knowledge-base content was found for this question. "
            "Try rephrasing, or ask about CPU scheduling, memory management, deadlocks, "
            "process management, file systems, or error recovery."
        )

    lines = [
        "[OFFLINE MODE - extractive answer, no LLM API key configured]" if not fallback_reason
        else f"[OFFLINE MODE - extractive answer; the language model did not answer ({fallback_reason}), so these are the retrieved passages]",
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
    fallback_reason: Optional[str] = None  # why a configured provider did not answer
    for name, key, call in (("groq", groq_key, _call_groq), ("anthropic", anthropic_key, _call_anthropic), ("openai", openai_key, _call_openai)):
        if generated is None and key:
            generated, why = call(prompt, key)
            if generated:
                mode, fallback_reason = name, None
            else:
                fallback_reason = f"{name}: {why}"

    answer = generated if generated else _extractive_fallback(question, chunks, process, incident_facts, fallback_reason)
    result = {"answer": answer, "mode": mode, "sources": sources}
    if fallback_reason:
        result["fallback_reason"] = fallback_reason
    return result
