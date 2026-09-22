"""Chunking + hand-rolled TF-IDF index building for the knowledge base.

DESIGN NOTE (deliberate, not a shortcut):
This project intentionally implements TF-IDF + cosine similarity in pure
Python instead of pulling in sentence-transformers/faiss/chromadb/torch.
That keeps `pip install -r requirements.txt` fast and dependency-light, and
means the whole RAG pipeline runs fully offline with zero downloads and zero
API keys. The `retrieval.py` module only depends on the `TfidfIndex`
interface below (`.search(query, top_k) -> list[Chunk]`), so a real
embedding-based index could be swapped in later (e.g. sentence-transformers
+ a vector store) without touching any calling code in retrieval.py or
assistant.py.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

KB_DIR = Path(__file__).parent.parent.parent / "knowledge_base"

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z\-]+")

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "of", "to",
    "in", "on", "for", "is", "are", "was", "were", "be", "been", "being",
    "it", "its", "this", "that", "these", "those", "with", "as", "by", "at",
    "from", "into", "such", "can", "will", "may", "also", "which", "their",
    "there", "when", "where", "so", "not", "than", "over", "each", "other",
}


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS and len(t) > 2]


@dataclass
class Chunk:
    chunk_id: int
    source: str
    text: str
    term_freqs: Counter


def _split_into_chunks(text: str, max_chars: int = 600) -> list[str]:
    """Split on blank-line paragraph boundaries, then greedily group
    paragraphs up to ~max_chars so chunks stay topically coherent."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if current and len(current) + len(para) > max_chars:
            chunks.append(current.strip())
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current.strip())
    return chunks


def load_chunks(kb_dir: Path = KB_DIR) -> list[Chunk]:
    chunks: list[Chunk] = []
    cid = 0
    for path in sorted(kb_dir.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        for piece in _split_into_chunks(text):
            tokens = tokenize(piece)
            if not tokens:
                continue
            chunks.append(Chunk(chunk_id=cid, source=path.stem, text=piece, term_freqs=Counter(tokens)))
            cid += 1
    return chunks


class TfidfIndex:
    """A minimal TF-IDF index: term frequency * inverse document frequency,
    with cosine similarity used at query time (see retrieval.py)."""

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.idf: dict[str, float] = {}
        self.vectors: list[dict[str, float]] = []
        self._build()

    def _build(self) -> None:
        n_docs = len(self.chunks)
        doc_freq: Counter = Counter()
        for chunk in self.chunks:
            for term in chunk.term_freqs:
                doc_freq[term] += 1

        self.idf = {
            term: math.log((1 + n_docs) / (1 + df)) + 1.0
            for term, df in doc_freq.items()
        }

        for chunk in self.chunks:
            total_terms = sum(chunk.term_freqs.values())
            vec = {}
            for term, count in chunk.term_freqs.items():
                tf = count / total_terms
                vec[term] = tf * self.idf.get(term, 0.0)
            self.vectors.append(vec)

    def vectorize_query(self, query: str) -> dict[str, float]:
        tokens = tokenize(query)
        if not tokens:
            return {}
        counts = Counter(tokens)
        total = sum(counts.values())
        return {term: (count / total) * self.idf.get(term, 0.0) for term, count in counts.items()}


def build_index(kb_dir: Path = KB_DIR) -> TfidfIndex:
    return TfidfIndex(load_chunks(kb_dir))
