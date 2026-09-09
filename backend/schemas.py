"""Pydantic request/response models."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    department: str = "all"
    mode: Literal["hybrid", "docs_only", "general"] = "hybrid"


class FeedbackRequest(BaseModel):
    answer_id: str
    query: str = ""
    rating: Literal["up", "down"]
    reason: Optional[str] = None


class Citation(BaseModel):
    source: int
    document: str = ""
    section: str = ""
    why: str = ""


class QueryResponse(BaseModel):
    answer_id: str
    query: str
    department: str
    mode: str
    answer: str
    citations: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    confidence: str = "medium"
    source_type: str
    used_general_knowledge: bool = False
    assumptions: str = ""
    next_action: str = ""
    top_score: float = 0.0
    latency_ms: int = 0
