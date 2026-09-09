"""FastAPI application: serves the REST API AND the static frontend.

Single deployable service — one `uvicorn backend.main:app` runs everything.
Authentication + role-based access control protect the API.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import agent, auth, database, ingestion
from .config import get_settings
from .llm import LLMError, LLMNotConfigured
from .schemas import (
    FeedbackRequest, LoginRequest, QueryRequest, QueryResponse, RegisterRequest,
)

settings = get_settings()
app = FastAPI(
    title="Infosys AI Knowledge Assistant (Enterprise GPT)",
    description="Governed, citation-backed enterprise knowledge assistant with a "
                "general-knowledge fallback, authentication and role-based access.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# Initialise schema + default accounts at import time so the app is ready
# regardless of how it is launched (uvicorn, gunicorn, TestClient).
database.init_db()
auth.seed_default_users()


@app.on_event("startup")
def _startup() -> None:
    database.init_db()
    auth.seed_default_users()


# --------------------------------------------------------------------------
# Auth dependencies
# --------------------------------------------------------------------------
def admin_user(user: dict[str, Any] = Depends(auth.current_user)) -> dict[str, Any]:
    return auth.require_admin(user)


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
# Authentication
# --------------------------------------------------------------------------
@app.post("/api/auth/register")
def register(req: RegisterRequest) -> dict:
    try:
        user = auth.register_user(
            email=req.email, password=req.password, name=req.name,
            department=req.department, role="employee",  # self-signup is always employee
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    token = auth.create_token(user["id"])
    return {"token": token, "user": user}


@app.post("/api/auth/login")
def login(req: LoginRequest) -> dict:
    try:
        user = auth.authenticate(req.email, req.password)
    except ValueError as e:
        raise HTTPException(401, str(e))
    token = auth.create_token(user["id"])
    return {"token": token, "user": auth._public(user)}


@app.get("/api/auth/me")
def me(user: dict[str, Any] = Depends(auth.current_user)) -> dict:
    return {"user": auth._public(user)}


@app.get("/api/auth/users")
def users(_: dict[str, Any] = Depends(admin_user)) -> dict:
    return {"users": database.list_users()}


# --------------------------------------------------------------------------
# Documents  (managing documents is admin-only)
# --------------------------------------------------------------------------
@app.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    department: str = Form("general"),
    doc_type: str = Form("document"),
    owner: str = Form(""),
    confidentiality: str = Form("internal"),
    effective_date: str = Form(""),
    _: dict[str, Any] = Depends(admin_user),
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
    except LLMError as e:
        raise HTTPException(502, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return JSONResponse(result)


@app.get("/api/documents")
def documents(_: dict[str, Any] = Depends(admin_user)) -> dict:
    return {"documents": database.list_documents()}


@app.delete("/api/documents/{document_id}")
def remove_document(document_id: str, _: dict[str, Any] = Depends(admin_user)) -> dict:
    ok = database.delete_document(document_id)
    if not ok:
        raise HTTPException(404, "Document not found.")
    return {"deleted": document_id}


# --------------------------------------------------------------------------
# Query / answer  (any authenticated user; access-scoped to their role/dept)
# --------------------------------------------------------------------------
@app.post("/api/query", response_model=QueryResponse)
def query(req: QueryRequest, user: dict[str, Any] = Depends(auth.current_user)) -> QueryResponse:
    visibility = auth.visibility_for(user, req.department)
    try:
        result = agent.answer_query(
            req.query, department=req.department, mode=req.mode, visibility=visibility,
        )
    except LLMNotConfigured as e:
        raise HTTPException(503, str(e))
    except LLMError as e:
        raise HTTPException(502, str(e))
    return QueryResponse(**result)


@app.get("/api/sources/{answer_id}")
def sources(answer_id: str, _: dict[str, Any] = Depends(auth.current_user)) -> dict:
    data = agent.get_answer_sources(answer_id)
    if data is None:
        raise HTTPException(404, "Answer not found.")
    return data


# --------------------------------------------------------------------------
# Feedback (any user) & analytics (admin-only)
# --------------------------------------------------------------------------
@app.post("/api/feedback")
def feedback(req: FeedbackRequest, _: dict[str, Any] = Depends(auth.current_user)) -> dict:
    fid = database.add_feedback(req.answer_id, req.query, req.rating, req.reason)
    return {"feedback_id": fid, "status": "recorded"}


@app.get("/api/analytics/quality")
def analytics(_: dict[str, Any] = Depends(admin_user)) -> dict:
    return database.analytics_summary()


# --------------------------------------------------------------------------
# Static frontend (served last so /api/* takes precedence)
# --------------------------------------------------------------------------
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(FRONTEND_DIR / "index.html"))
