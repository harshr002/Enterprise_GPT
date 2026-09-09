# Security & Governance Notes

## Secrets
- `GEMINI_API_KEY`, `DATABASE_PATH` and all configuration are read from
  environment variables (see `.env.example`). No secrets live in the frontend
  or in source control (`.env` is git-ignored).
- The frontend never talks to the LLM directly — all model and embedding calls
  happen server-side in `backend/llm.py`.

## Access control (implemented)
- **Department-filtered retrieval:** queries can be scoped to a department; the
  retriever only returns that department's chunks plus shared `general` content.
- **Confidentiality metadata:** every document carries a confidentiality tag
  (`internal` / `restricted` / `public`) surfaced in the UI and source cards.
- **Grounded-only source exposure:** raw document snippets are only returned for
  answers that are actually grounded in documents — general-knowledge answers do
  not leak source text.

## Auditability (implemented)
- Every answer stores the exact sources it was grounded on, retrievable via
  `GET /api/sources/{answer_id}`.
- Every query is logged (`query_log`): department, mode, source type, top
  similarity score and latency — feeding the quality dashboard.
- Feedback (👍/👎) is stored against the answer id.

## Hardening for production (recommended next steps)
These are intentionally left as extension points for a first release:
- **Authentication:** add OIDC / SSO and derive the user's real role and
  department from the token instead of trusting the client-supplied department.
- **Row-level authorization:** enforce document-level ACLs in `retrieval.py`
  based on the authenticated user's entitlements.
- **PII / redaction:** run a redaction pass on ingested content where required.
- **Rate limiting & abuse protection** on `/api/query` and `/api/documents/upload`.
- **Transport security:** terminate TLS at your host/proxy (Render/Railway/Fly
  provide HTTPS automatically).
- **Managed vector DB** with tenant isolation for multi-department scale.

## Data handling
- Uploaded documents are parsed and stored (chunks + embeddings) in the SQLite
  database at `DATABASE_PATH`. Deleting a document removes its chunks.
- Document text is sent to the configured LLM provider (Google Gemini) for
  embedding and answer synthesis. Review your provider's data-use terms before
  ingesting sensitive content, and restrict ingestion to approved material.
