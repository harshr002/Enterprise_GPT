"""SQLite storage: documents, chunks (+embeddings), feedback, audit logs.

We keep embeddings inside SQLite as JSON blobs and do cosine similarity in
numpy. For an enterprise-scale deployment you would swap `retrieval.py` for a
real vector DB (Qdrant / Chroma / pgvector) — the interface is intentionally
small so that change is localized.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Any

from .config import get_settings

_local = threading.local()


def _connect() -> sqlite3.Connection:
    settings = get_settings()
    conn = sqlite3.connect(str(settings.database_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def get_conn() -> sqlite3.Connection:
    """One connection per thread (FastAPI worker threads)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id            TEXT PRIMARY KEY,
            email         TEXT UNIQUE NOT NULL,
            name          TEXT,
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'employee',
            department    TEXT NOT NULL DEFAULT 'general',
            created_at    REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS documents (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            department    TEXT NOT NULL DEFAULT 'general',
            doc_type      TEXT NOT NULL DEFAULT 'document',
            owner         TEXT,
            confidentiality TEXT NOT NULL DEFAULT 'internal',
            effective_date  TEXT,
            status        TEXT NOT NULL DEFAULT 'indexed',
            chunk_count   INTEGER NOT NULL DEFAULT 0,
            char_count    INTEGER NOT NULL DEFAULT 0,
            created_at    REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id           TEXT PRIMARY KEY,
            document_id  TEXT NOT NULL,
            department   TEXT NOT NULL,
            section      TEXT,
            ordinal      INTEGER NOT NULL,
            text         TEXT NOT NULL,
            embedding    TEXT,          -- JSON array of floats
            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS feedback (
            id          TEXT PRIMARY KEY,
            answer_id   TEXT,
            query       TEXT,
            rating      TEXT,           -- up | down
            reason      TEXT,
            created_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS query_log (
            id            TEXT PRIMARY KEY,
            query         TEXT,
            department    TEXT,
            mode          TEXT,
            source_type   TEXT,         -- documents | general_knowledge | mixed | none
            top_score     REAL,
            latency_ms    INTEGER,
            created_at    REAL NOT NULL
        );
        """
    )
    conn.commit()


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------
def create_user(email: str, name: str, password_hash: str,
                role: str, department: str) -> dict[str, Any]:
    conn = get_conn()
    uid = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO users (id, email, name, password_hash, role, department, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (uid, email, name, password_hash, role, department, time.time()),
    )
    conn.commit()
    return get_user_by_id(uid)


def get_user_by_email(email: str) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def count_users() -> int:
    conn = get_conn()
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def list_users() -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, email, name, role, department, created_at FROM users ORDER BY created_at"
    ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# Documents & chunks
# --------------------------------------------------------------------------
def create_document(meta: dict[str, Any]) -> str:
    conn = get_conn()
    doc_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO documents
           (id, name, department, doc_type, owner, confidentiality,
            effective_date, status, chunk_count, char_count, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            doc_id,
            meta["name"],
            meta.get("department", "general"),
            meta.get("doc_type", "document"),
            meta.get("owner"),
            meta.get("confidentiality", "internal"),
            meta.get("effective_date"),
            "processing",
            0,
            meta.get("char_count", 0),
            time.time(),
        ),
    )
    conn.commit()
    return doc_id


def add_chunks(document_id: str, department: str, chunks: list[dict[str, Any]]) -> None:
    conn = get_conn()
    rows = [
        (
            str(uuid.uuid4()),
            document_id,
            department,
            c.get("section"),
            c["ordinal"],
            c["text"],
            json.dumps(c["embedding"]) if c.get("embedding") is not None else None,
        )
        for c in chunks
    ]
    conn.executemany(
        """INSERT INTO chunks (id, document_id, department, section, ordinal, text, embedding)
           VALUES (?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()


def mark_document_indexed(document_id: str, chunk_count: int) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE documents SET status='indexed', chunk_count=? WHERE id=?",
        (chunk_count, document_id),
    )
    conn.commit()


def list_documents() -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM documents ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_document(document_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    return dict(row) if row else None


def delete_document(document_id: str) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM documents WHERE id=?", (document_id,))
    conn.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
    conn.commit()
    return cur.rowcount > 0


def iter_chunks(departments: list[str] | None = None,
                confidentialities: list[str] | None = None) -> list[dict[str, Any]]:
    """Return all chunks with doc metadata, filtered by access rules.

    departments / confidentialities of None mean "no restriction" (admins).
    """
    conn = get_conn()
    sql = """
        SELECT c.id, c.document_id, c.section, c.ordinal, c.text, c.embedding,
               d.name AS document_name, d.department, d.doc_type,
               d.confidentiality, d.effective_date, d.owner
        FROM chunks c JOIN documents d ON c.document_id = d.id
        WHERE c.embedding IS NOT NULL
    """
    params: list[Any] = []
    if departments:
        placeholders = ",".join("?" for _ in departments)
        sql += f" AND c.department IN ({placeholders})"
        params.extend(departments)
    if confidentialities:
        placeholders = ",".join("?" for _ in confidentialities)
        sql += f" AND d.confidentiality IN ({placeholders})"
        params.extend(confidentialities)
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["embedding"] = json.loads(d["embedding"]) if d["embedding"] else None
        out.append(d)
    return out


# --------------------------------------------------------------------------
# Feedback & logging
# --------------------------------------------------------------------------
def
