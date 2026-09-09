"""FastAPI application: serves the REST API AND the static frontend.

Single deployable service — one `uvicorn backend.main:app` runs everything.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import agent, database, ingestion
from .config import get_settings
from .llm import LLMNotConfigured
from .schemas import FeedbackRequest, QueryRequest, QueryResponse

settings = get_settings()
app = FastAPI(
    title="Infosys AI Knowledge Assistant (Enterprise GPT)",
    description="Governed, citation-backed enterprise knowledge assistant with a "
                "general-knowledge fallback.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# Initialise the schema at import time so the DB is ready regardless of how the
# app is launched (uvicorn, gunicorn, TestClient). init_db() is idempotent.
database.init_db()


@app.on_event("startup")
def _startup() -> None:
    database.init_db()


# --------------------------------------------------------------------------
# Health / status
# --------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm_configured": settings.llm_ready,
        "chat_model": settings.chat_model,
        "embed_model": settings.embed_model,
    }


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------
@app.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    department: str = Form("general"),
    doc_type: str = Form("document"),
    owner: str = Form(""),
    confidentiality: str = Form("internal"),
    effective_date: str = Form(""),
) -> JSONResponse:
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file.")
    meta = {
        "name": file.filename,
        "department": department or "general",
        "doc_type": doc_type or "document",
        "owner": owner or None,
        "confidentiality": confidentiality or "internal",
        "effective_date": effective_date or None,
    }
    try:
        result = ingestion.ingest_document(file.filename, raw, meta)
    except LLMNotConfigured as e:
        raise HTTPException(503, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return JSONResponse(result)


@app.get("/api/documents")
def documents() -> dict:
    return {"documents": database.list_documents()}


@app.delete("/api/documents/{document_id}")
def remove_document(document_id: str) -> dict:
    ok = database.delete_document(document_id)
    if not ok:
        raise HTTPException(404, "Document not found.")
    return {"deleted": document_id}


# --------------------------------------------------------------------------
# Query / answer
# --------------------------------------------------------------------------
@app.post("/api/query", response_model=QueryResponse)
def query(req: QueryRequest) -> QueryResponse:
    try:
        result = agent.answer_query(req.query, department=req.department, mode=req.mode)
    except LLMNotConfigured as e:
        raise HTTPException(503, str(e))
    return QueryResponse(**result)


@app.get("/api/sources/{answer_id}")
def sources(answer_id: str) -> dict:
    data = agent.get_answer_sources(answer_id)
    if data is None:
        raise HTTPException(404, "Answer not found.")
    return data


# --------------------------------------------------------------------------
# Feedback & analytics
# --------------------------------------------------------------------------
@app.post("/api/feedback")
def feedback(req: FeedbackRequest) -> dict:
    fid = database.add_feedback(req.answer_id, req.query, req.rating, req.reason)
    return {"feedback_id": fid, "status": "recorded"}


@app.get("/api/analytics/quality")
def analytics() -> dict:
    return database.analytics_summary()


# --------------------------------------------------------------------------
# Static frontend (served last so /api/* takes precedence)
# --------------------------------------------------------------------------
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(FRONTEND_DIR / "index.html"))
