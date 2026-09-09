"""Vector retrieval over stored chunk embeddings (numpy cosine similarity).

Swap this module for Qdrant / Chroma / pgvector to scale beyond ~50k chunks;
the public function `search()` is the only thing the agent depends on.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from . import database
from .config import get_settings
from .llm import embed_query


def _cosine(matrix: np.ndarray, vec: np.ndarray) -> np.ndarray:
    m_norm = np.linalg.norm(matrix, axis=1)
    v_norm = np.linalg.norm(vec)
    denom = m_norm * v_norm
    denom[denom == 0] = 1e-9
    return (matrix @ vec) / denom


def search(query: str, departments: list[str] | None = None,
           top_k: int | None = None) -> list[dict[str, Any]]:
    """Return top_k chunks ranked by cosine similarity, with metadata & score."""
    settings = get_settings()
    top_k = top_k or settings.top_k

    rows = database.iter_chunks(departments)
    if not rows:
        return []

    q_vec = np.asarray(embed_query(query), dtype=np.float32)
    matrix = np.asarray([r["embedding"] for r in rows], dtype=np.float32)
    scores = _cosine(matrix, q_vec)

    order = np.argsort(scores)[::-1][:top_k]
    results = []
    for idx in order:
        r = rows[int(idx)]
        results.append(
            {
                "chunk_id": r["id"],
                "document_id": r["document_id"],
                "document_name": r["document_name"],
                "department": r["department"],
                "doc_type": r["doc_type"],
                "section": r["section"],
                "confidentiality": r["confidentiality"],
                "effective_date": r["effective_date"],
                "owner": r["owner"],
                "text": r["text"],
                "score": round(float(scores[int(idx)]), 4),
            }
        )
    return results
