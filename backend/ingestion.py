"""Document intake: parse -> chunk (section-aware) -> embed -> store."""
from __future__ import annotations

import io
import re
from typing import Any

from . import database
from .llm import embed_texts

# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def extract_text(filename: str, raw: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        return _extract_pdf(raw)
    if name.endswith(".docx"):
        return _extract_docx(raw)
    # txt / md / csv / anything text-ish
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _extract_pdf(raw: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    parts = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            parts.append(f"[Page {i + 1}]\n{text}")
    return "\n\n".join(parts)


def _extract_docx(raw: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(raw))
    parts = []
    for p in doc.paragraphs:
        if p.text.strip():
            # Prefix headings so the chunker can detect sections.
            if p.style and p.style.name and p.style.name.lower().startswith("heading"):
                parts.append(f"## {p.text.strip()}")
            else:
                parts.append(p.text.strip())
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Chunking (section-aware, with overlap)
# --------------------------------------------------------------------------
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6}\s+.+|\[Page \d+\]|[A-Z0-9][A-Z0-9 .\-]{3,60}:?)\s*$")

MAX_CHARS = 1100
OVERLAP = 150


def chunk_text(text: str) -> list[dict[str, Any]]:
    """Split into ~MAX_CHARS chunks, tracking the nearest heading as section."""
    lines = text.splitlines()
    chunks: list[dict[str, Any]] = []
    current_section = "Introduction"
    buffer: list[str] = []
    buf_len = 0
    ordinal = 0

    def flush() -> None:
        nonlocal buffer, buf_len, ordinal
        body = "\n".join(buffer).strip()
        if body:
            chunks.append({"ordinal": ordinal, "section": current_section, "text": body})
            ordinal += 1
        buffer = []
        buf_len = 0

    for line in lines:
        stripped = line.strip()
        is_heading = bool(stripped) and bool(_HEADING_RE.match(stripped)) and len(stripped) < 80
        if is_heading:
            flush()
            current_section = re.sub(r"^#{1,6}\s+", "", stripped).strip("# :")
            continue

        buffer.append(line)
        buf_len += len(line) + 1
        if buf_len >= MAX_CHARS:
            # keep a small overlap tail for context continuity
            tail = "\n".join(buffer)[-OVERLAP:]
            flush()
            if tail.strip():
                buffer = [tail]
                buf_len = len(tail)

    flush()
    return chunks


# --------------------------------------------------------------------------
# Full ingest pipeline
# --------------------------------------------------------------------------
def ingest_document(filename: str, raw: bytes, meta: dict[str, Any]) -> dict[str, Any]:
    text = extract_text(filename, raw)
    if not text.strip():
        raise ValueError("No extractable text found in the document.")

    meta = {**meta, "name": meta.get("name") or filename, "char_count": len(text)}
    doc_id = database.create_document(meta)

    chunks = chunk_text(text)
    if not chunks:
        chunks = [{"ordinal": 0, "section": "Document", "text": text[:MAX_CHARS]}]

    # Embed chunk bodies in one batch.
    embeddings = embed_texts([c["text"] for c in chunks])
    for c, emb in zip(chunks, embeddings):
        c["embedding"] = emb

    database.add_chunks(doc_id, meta.get("department", "general"), chunks)
    database.mark_document_indexed(doc_id, len(chunks))

    return {
        "document_id": doc_id,
        "name": meta["name"],
        "chunk_count": len(chunks),
        "char_count": len(text),
        "status": "indexed",
    }
