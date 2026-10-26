"""Cosine-similarity search over the TF-IDF index built in ingestion.py."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from rag.ingestion import Chunk, TfidfIndex, build_index


@dataclass
class SearchResult:
    chunk: Chunk
    score: float


def _cosine(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    # Iterate the smaller dict for speed.
    if len(vec_a) > len(vec_b):
        vec_a, vec_b = vec_b, vec_a
    dot = sum(weight * vec_b.get(term, 0.0) for term, weight in vec_a.items())
    norm_a = math.sqrt(sum(w * w for w in vec_a.values()))
    norm_b = math.sqrt(sum(w * w for w in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


@lru_cache(maxsize=1)
def get_index() -> TfidfIndex:
    return build_index()


def search(query: str, top_k: int = 3, source_filter: list[str] | None = None, index: TfidfIndex | None = None) -> list[SearchResult]:
    index = index or get_index()
    query_vec = index.vectorize_query(query)
    results = []
    for chunk, vec in zip(index.chunks, index.vectors):
        if source_filter and chunk.source not in source_filter:
            continue
        score = _cosine(query_vec, vec)
        if score > 0:
            results.append(SearchResult(chunk=chunk, score=score))
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]
