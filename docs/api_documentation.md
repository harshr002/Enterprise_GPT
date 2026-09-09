# API Documentation

Base URL: `http://localhost:8000` (local) or your deployed URL.
Interactive Swagger UI is auto-generated at **`/docs`**.

---

### `GET /api/health`
Returns service + model status.
```json
{ "status": "ok", "llm_configured": true,
  "chat_model": "gemini-2.0-flash", "embed_model": "text-embedding-004" }
```

### `POST /api/documents/upload`
Multipart form upload. Fields:
| field | type | notes |
|-------|------|-------|
| `file` | file | PDF, DOCX, TXT, MD, CSV |
| `department` | text | delivery / hr / sales / engineering / operations / general |
| `doc_type` | text | sop / policy / manual / runbook / playbook / document |
| `owner` | text | optional |
| `confidentiality` | text | internal / restricted / public |
| `effective_date` | text | ISO date, optional |

Response:
```json
{ "document_id": "…", "name": "hr_leave_policy.md",
  "chunk_count": 6, "char_count": 1423, "status": "indexed" }
```

### `GET /api/documents`
```json
{ "documents": [ { "id": "…", "name": "…", "department": "hr",
  "doc_type": "policy", "confidentiality": "internal",
  "chunk_count": 6, "status": "indexed", "created_at": 1757... } ] }
```

### `DELETE /api/documents/{document_id}`
Removes the document and its chunks. `{ "deleted": "<id>" }`

### `POST /api/query`
Request:
```json
{ "query": "What is the leave carry-forward policy?",
  "department": "hr", "mode": "hybrid" }
```
`mode` ∈ `hybrid` | `docs_only` | `general`.

Response:
```json
{
  "answer_id": "…",
  "answer": "Employees may carry forward up to 10 unused days [1]...",
  "citations": [ { "source": 1, "document": "hr_leave_policy.md",
                   "section": "Carry Forward", "why": "states the 10-day cap" } ],
  "sources": [ { "source": 1, "document_name": "hr_leave_policy.md",
                 "section": "Carry Forward", "score": 0.82, "snippet": "..." } ],
  "confidence": "high",
  "source_type": "documents",
  "used_general_knowledge": false,
  "assumptions": "",
  "next_action": "Confirm exceptions with HR Operations.",
  "top_score": 0.82,
  "latency_ms": 940
}
```
`source_type` ∈ `documents` | `general_knowledge` | `insufficient` | `none`.

### `GET /api/sources/{answer_id}`
Returns the retrieved sources an answer was grounded on (audit trail).

### `POST /api/feedback`
```json
{ "answer_id": "…", "query": "…", "rating": "up", "reason": null }
```
`rating` ∈ `up` | `down`.

### `GET /api/analytics/quality`
```json
{ "total_documents": 4, "total_chunks": 22, "total_queries": 37,
  "no_answer_rate": 5.4, "citation_coverage": 78.4, "avg_latency_ms": 910,
  "feedback_up": 12, "feedback_down": 1,
  "queries_by_department": [ { "department": "hr", "c": 14 } ],
  "repeated_questions": [ { "query": "leave policy", "c": 3 } ] }
```

## Error codes
| code | meaning |
|------|---------|
| 422 | Unprocessable — e.g. no extractable text in the file |
| 404 | Document / answer not found |
| 503 | LLM not configured (missing `GEMINI_API_KEY`) |
