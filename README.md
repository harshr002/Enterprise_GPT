# Infosys AI Knowledge Assistant — Enterprise GPT

A governed, **citation-backed** enterprise knowledge assistant. Upload approved
internal documents (SOPs, HR policies, project manuals, engineering runbooks,
sales playbooks); employees ask natural-language questions and get concise
answers **grounded in your documents with citations** — and, when the documents
don't cover the question, the assistant **answers from general knowledge like a
web search**, clearly labelled so it's never mistaken for internal policy.

Built as a **single deployable service**: one FastAPI backend serves the REST
API *and* the polished web front end. No separate frontend build step, no
external vector database required to get started.

![architecture](docs/screenshots/placeholder.md)

---

## ✨ What it does

- **Ask a question** — retrieval-augmented answers grounded in approved sources, with inline `[1]` citations and expandable source cards.
- **Answer anything (like Google)** — a *Hybrid* mode falls back to general knowledge when your docs don't cover the question; an *Ask anything* mode ignores documents entirely. Both are clearly labelled.
- **Docs-only mode** — strict grounding: if the evidence is weak, it returns a cautious "no strong match" instead of guessing.
- **Knowledge base console** — upload PDF / DOCX / TXT / MD / CSV, tag department, owner, confidentiality and effective date; the pipeline parses → chunks → embeds → indexes.
- **Department-aware retrieval** — filter answers to a department's approved content.
- **Usage & quality dashboard** — query volume, citation coverage, no-answer rate, latency, feedback, and repeated-question (knowledge-gap) detection.
- **Audit trail** — every answer records the exact sources it was grounded on.

## 🧱 Architecture

```
Browser (frontend/)  ──►  FastAPI (backend/main.py)
                              │
      ┌───────────────────────┼─────────────────────────┐
      ▼                       ▼                          ▼
 ingestion.py            agent.py                   database.py
 parse→chunk→embed   classify→retrieve→route→    SQLite: docs, chunks,
                     synthesize w/ citations      embeddings, feedback, logs
      │                       │
      ▼                       ▼
   llm.py  ◄───────────  retrieval.py
 (Gemini chat +          (numpy cosine over
  embeddings, REST)       stored embeddings)
```

**Answering flow:** query → embed → vector search (permission/department
filtered) → if the top match clears the relevance threshold, synthesize a
**grounded, cited** answer; otherwise (in Hybrid) answer from **general
knowledge**, labelled as such. Everything is logged for the analytics dashboard.

See [`docs/architecture.md`](docs/architecture.md) for the full narrative.

## 🛠 Tech stack

| Layer | Choice |
|------|--------|
| Backend / API | FastAPI + Uvicorn |
| LLM (answers) | Google Gemini (`gemini-2.0-flash`, configurable) |
| Embeddings | Gemini `text-embedding-004` |
| Retrieval | numpy cosine similarity over SQLite-stored embeddings (swappable for Qdrant / Chroma / pgvector) |
| Storage | SQLite (documents, chunks, embeddings, feedback, query logs) |
| Document parsing | pypdf, python-docx, plain text |
| Frontend | Vanilla HTML/CSS/JS (no build step), light + dark aware |

Gemini is used because it has a **generous free tier** and needs no heavy local
ML models — so the whole thing deploys on a free web dyno.

---

## 🚀 Quick start (local, ~2 minutes)

**Prerequisites:** Python 3.10+ and a free Gemini API key
(<https://aistudio.google.com/app/apikey>).

```bash
# 1. from the project folder
cp .env.example .env
#    then edit .env and paste your key into GEMINI_API_KEY

# 2. install + run (creates a venv automatically)
bash run.sh
```

Or manually:

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # add your GEMINI_API_KEY
python seed.py                # optional: load the 4 sample documents
uvicorn backend.main:app --reload --port 8000
```

Open **<http://localhost:8000>**.

Try: *“What is the leave carry-forward policy?”*, *“Steps to respond to a Sev-1
incident”*, or switch to **Ask anything** and try *“Explain retrieval-augmented
generation.”*

---

## ☁️ Deploy

Full step-by-step (Render, Railway, Docker, Fly.io) is in
[`docs/deployment.md`](docs/deployment.md). The short version:

### Render (recommended, free tier)
1. Push this repo to GitHub.
2. Render → **New + → Blueprint** and select the repo (it reads `render.yaml`).
3. Add the secret **`GEMINI_API_KEY`** in the dashboard.
4. Deploy. Your app is live at `https://<your-app>.onrender.com`.

### Docker (anywhere)
```bash
docker build -t enterprise-gpt .
docker run -p 8000:8000 -e GEMINI_API_KEY=your_key enterprise-gpt
```

> **After deploying, paste your live URL here:** `https://<your-app>.onrender.com`

---

## 📡 API reference (summary)

| Method | Endpoint | Purpose |
|-------|----------|---------|
| `GET`  | `/api/health` | Status + whether the LLM key is configured |
| `POST` | `/api/documents/upload` | Upload + index a document (multipart form) |
| `GET`  | `/api/documents` | List indexed documents |
| `DELETE` | `/api/documents/{id}` | Remove a document + its chunks |
| `POST` | `/api/query` | Ask a question `{query, department, mode}` |
| `GET`  | `/api/sources/{answer_id}` | Sources an answer was grounded on (audit) |
| `POST` | `/api/feedback` | Record 👍/👎 on an answer |
| `GET`  | `/api/analytics/quality` | Usage & quality metrics |

Interactive docs auto-generated at **`/docs`** (FastAPI Swagger UI).
Full details in [`docs/api_documentation.md`](docs/api_documentation.md).

## 📁 Repository structure

```
infosys-ai-knowledge-assistant/
├── backend/          FastAPI app, RAG agent, ingestion, retrieval, LLM, DB
├── frontend/         single-page UI (index.html, styles.css, app.js)
├── data/sample_docs/ 4 ready-to-index sample documents
├── docs/             architecture, deployment, API, security notes
├── seed.py           load the sample docs into the index
├── requirements.txt  Dockerfile  render.yaml  run.sh  .env.example
```

## 🔐 Security notes
- All secrets (`GEMINI_API_KEY`, DB path) live in environment variables — never in frontend code.
- Retrieval is **department-filtered**, and documents carry a confidentiality tag; source snippets are only shown for grounded answers.
- Every answer keeps an audit record of the sources used.
See [`docs/security_notes.md`](docs/security_notes.md).

## 🧭 Modes at a glance
| Mode | Behaviour |
|------|-----------|
| **Hybrid** (default) | Documents first (cited); general-knowledge fallback, labelled |
| **Docs only** | Strictly from your documents; cautious "no match" if weak |
| **Ask anything** | Pure general knowledge, like a web search |

## Roadmap / extension points
- Swap `retrieval.py` for a managed vector DB (Qdrant / Chroma / pgvector).
- Add OIDC auth + real role-based access control at the API layer.
- Add MCP connectors so the agent can route to live document stores.

---
Built for the Infosys **AI Knowledge Assistant (Enterprise GPT)** brief.
