"""The Enterprise GPT agent: classify -> retrieve -> route -> synthesize.

Answering modes
---------------
- "hybrid" (default): answer from your documents WITH citations when the
  retrieved evidence is strong; otherwise fall back to general knowledge
  (like Google) and clearly label it as *not from your documents*.
- "docs_only": only answer from indexed documents; if evidence is weak,
  return a cautious no-answer response.
- "general": ignore documents, answer purely from the model's world
  knowledge (the "ask me anything" mode).
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from . import database, retrieval
from .config import get_settings
from .llm import generate_json, generate_text, LLMNotConfigured

# In-memory store of the sources used for each answer, so /api/sources/{id}
# can return exactly what an answer was grounded on (audit trail).
_ANSWER_SOURCES: dict[str, dict[str, Any]] = {}


GROUNDED_PROMPT = """You are the Infosys AI Knowledge Assistant (Enterprise GPT), \
an internal, citation-backed productivity assistant.

A user from the "{department}" area asked:
"{query}"

Below are passages retrieved from APPROVED internal documents. Each is tagged \
with a source number, document name and section.

{context}

INSTRUCTIONS:
- Answer ONLY using the passages above. Do not invent policy, numbers or steps.
- Cite every material claim using the source numbers like [1], [2].
- If the passages only partially answer the question, say what is covered and \
what is missing.
- If the passages do NOT contain enough evidence to answer, set \
"source_type" to "insufficient" and explain what document would be needed.
- Be concise and practical. Prefer clear steps for process/SOP questions.
- For HR/policy questions, be cautious: point to the official document and its \
effective date rather than interpreting beyond the text.

Return STRICT JSON with this schema:
{{
  "answer": "markdown answer with inline [n] citations",
  "citations": [{{"source": 1, "document": "name", "section": "section", "why": "what it supports"}}],
  "confidence": "high" | "medium" | "low",
  "source_type": "documents" | "insufficient",
  "assumptions": "any assumptions, or empty string",
  "next_action": "a short suggested next step for the user"
}}"""


HYBRID_FALLBACK_PROMPT = """You are the Infosys AI Knowledge Assistant (Enterprise GPT).

The user asked:
"{query}"

Their internal knowledge base did NOT contain a strong match for this question, \
so answer from your own general knowledge (like a helpful web search would), \
while being clearly honest that this is general knowledge and not sourced from \
the organisation's approved documents.

INSTRUCTIONS:
- Give a genuinely useful, accurate answer from general world knowledge.
- Do NOT fabricate Infosys-specific internal policies, numbers or approvals.
- If the question really needs an internal document to answer correctly, say so \
and suggest the user upload or check that document.

Return STRICT JSON with this schema:
{{
  "answer": "markdown answer",
  "citations": [],
  "confidence": "high" | "medium" | "low",
  "source_type": "general_knowledge",
  "assumptions": "",
  "next_action": "a short suggested next step"
}}"""


GENERAL_PROMPT = """You are a knowledgeable, accurate assistant (general "ask me \
anything" mode).

Question:
"{query}"

Answer helpfully and accurately from general world knowledge. Be concise but \
complete. If you are unsure or the topic is beyond reliable knowledge, say so.

Return STRICT JSON with this schema:
{{
  "answer": "markdown answer",
  "citations": [],
  "confidence": "high" | "medium" | "low",
  "source_type": "general_knowledge",
  "assumptions": "",
  "next_action": ""
}}"""


def _format_context(hits: list[dict[str, Any]]) -> str:
    blocks = []
    for i, h in enumerate(hits, start=1):
        blocks.append(
            f"[{i}] Document: {h['document_name']} | Section: {h.get('section') or '—'} "
            f"| Dept: {h['department']} | Effective: {h.get('effective_date') or 'n/a'} "
            f"| Relevance: {h['score']}\n{h['text']}"
        )
    return "\n\n".join(blocks)


def _sources_payload(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source": i,
            "document_id": h["document_id"],
            "document_name": h["document_name"],
            "section": h.get("section"),
            "department": h["department"],
            "confidentiality": h["confidentiality"],
            "effective_date": h.get("effective_date"),
            "owner": h.get("owner"),
            "score": h["score"],
            "snippet": h["text"][:600],
        }
        for i, h in enumerate(hits, start=1)
    ]


def answer_query(query: str, department: str = "all", mode: str = "hybrid") -> dict[str, Any]:
    settings = get_settings()
    started = time.time()
    answer_id = str(uuid.uuid4())

    departments = None if department in ("all", "", None) else [department, "general"]

    # ---- retrieval (skipped in pure general mode) --------------------
    hits: list[dict[str, Any]] = []
    top_score = 0.0
    if mode != "general":
        try:
            hits = retrieval.search(query, departments=departments)
        except LLMNotConfigured:
            raise
        top_score = hits[0]["score"] if hits else 0.0

    strong = top_score >= settings.relevance_threshold
    route = "none"

    # ---- routing -----------------------------------------------------
    if mode == "general" or (mode == "hybrid" and not hits):
        result = generate_json(GENERAL_PROMPT.format(query=query))
        route = "general_knowledge"

    elif mode == "docs_only":
        if not strong:
            result = {
                "answer": (
                    "I couldn't find enough evidence in your indexed documents to "
                    "answer this confidently. Try rephrasing, selecting the right "
                    "department, or uploading the relevant document."
                ),
                "citations": [],
                "confidence": "low",
                "source_type": "none",
                "assumptions": "",
                "next_action": "Upload or select the document that covers this topic.",
            }
            route = "none"
        else:
            result = generate_json(
                GROUNDED_PROMPT.format(
                    department=department, query=query, context=_format_context(hits)
                )
            )
            route = "documents"

    else:  # hybrid with hits
        if strong:
            result = generate_json(
                GROUNDED_PROMPT.format(
                    department=department, query=query, context=_format_context(hits)
                )
            )
            # The model may still decide evidence is insufficient -> fall back.
            if result.get("source_type") == "insufficient":
                fb = generate_json(HYBRID_FALLBACK_PROMPT.format(query=query))
                if fb:
                    result = fb
                    result["source_type"] = "general_knowledge"
                    route = "general_knowledge"
                else:
                    route = "documents"
            else:
                route = "documents"
        else:
            result = generate_json(HYBRID_FALLBACK_PROMPT.format(query=query))
            route = "general_knowledge"

    # ---- defensive defaults -----------------------------------------
    if not result or not result.get("answer"):
        result = {
            "answer": "Sorry, I wasn't able to generate an answer for that just now. "
                      "Please try again.",
            "citations": [],
            "confidence": "low",
            "source_type": route,
            "assumptions": "",
            "next_action": "",
        }

    # Only expose the source cards when the answer is actually grounded.
    used_sources = _sources_payload(hits) if route == "documents" else []
    source_type = result.get("source_type", route)

    payload = {
        "answer_id": answer_id,
        "query": query,
        "department": department,
        "mode": mode,
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
        "sources": used_sources,
        "confidence": result.get("confidence", "medium"),
        "source_type": source_type,
        "used_general_knowledge": source_type == "general_knowledge",
        "assumptions": result.get("assumptions", ""),
        "next_action": result.get("next_action", ""),
        "top_score": top_score,
        "latency_ms": int((time.time() - started) * 1000),
    }

    # audit trail + analytics
    _ANSWER_SOURCES[answer_id] = {
        "query": query,
        "sources": _sources_payload(hits),
        "source_type": source_type,
    }
    database.log_query(
        query=query, department=department, mode=mode, source_type=source_type,
        top_score=top_score, latency_ms=payload["latency_ms"],
    )
    return payload


def get_answer_sources(answer_id: str) -> dict[str, Any] | None:
    return _ANSWER_SOURCES.get(answer_id)
