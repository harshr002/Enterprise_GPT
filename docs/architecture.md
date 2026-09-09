# Architecture

## Overview
The system follows an enterprise knowledge lifecycle: documents are uploaded and
indexed, employee queries are classified and routed, relevant sources are
retrieved with permission filtering, and the LLM synthesizes a cited answer with
an audit trail and feedback capture.

## Components

### Ingestion (`backend/ingestion.py`)
- **Parse** PDF (pypdf), DOCX (python-docx) or text.
- **Chunk** section-aware: detects headings/markers and splits into ~1,100-char
  chunks with a small overlap, keeping the nearest section label per chunk.
- **Embed** each chunk with Gemini `text-embedding-004`.
- **Store** chunks + embeddings + metadata in SQLite.

### Retrieval (`backend/retrieval.py`)
- Embeds the query, computes cosine similarity in numpy against stored chunk
  embeddings, and returns the top-K with scores and metadata.
- Supports **department filtering** (a department's docs plus shared `general`).
- Deliberately small interface (`search()`), so it can be swapped for a managed
  vector DB without touching the agent.

### Agent (`backend/agent.py`)
The decision logic:

1. **Classify by mode** — `hybrid`, `docs_only`, or `general`.
2. **Retrieve** (skipped in pure general mode).
3. **Route:**
   - Top similarity ≥ `RELEVANCE_THRESHOLD` → **grounded synthesis** with
     citations. If the model itself judges the evidence insufficient, Hybrid
     falls back to general knowledge.
   - Below threshold → **general knowledge** (Hybrid) or a cautious **no-answer**
     (docs-only).
4. **Structured output** — the LLM returns strict JSON: `answer`, `citations`,
   `confidence`, `source_type`, `assumptions`, `next_action`.
5. **Audit + log** — the sources used are stored per `answer_id`; the query is
   logged for analytics.

### LLM (`backend/llm.py`)
Thin Gemini REST client: `embed_texts`, `embed_query`, `generate_json`,
`generate_text`. Swap this file to change providers.

### Storage (`backend/database.py`)
SQLite tables: `documents`, `chunks` (with JSON embeddings), `feedback`,
`query_log`. Also computes the analytics summary.

### API + Frontend (`backend/main.py`, `frontend/`)
FastAPI exposes the REST API and serves the single-page UI. The UI has three
views: **Ask a question**, **Knowledge base**, and **Usage & quality**.

## Data flow (query)
```
user query
   │  (mode, department)
   ▼
embed query ──► vector search (dept-filtered) ──► top-K chunks + scores
   │
   ├── strong match ──► grounded synthesis (cited) ─┐
   │                         │ insufficient?         │
   │                         └──► general fallback ──┤
   └── weak match ──► general knowledge / no-answer ─┤
                                                     ▼
                              structured JSON answer + sources + audit + log
```

## Why these choices
- **Single service** keeps deployment trivial (one dyno, one command).
- **SQLite + numpy** removes the need to provision a vector DB for a first
  release, while `retrieval.py` stays swappable for scale.
- **Gemini** gives a strong free tier and hosted embeddings, avoiding heavy
  local models so the container stays small and free-tier friendly.
