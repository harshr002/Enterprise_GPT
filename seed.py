"""Seed the knowledge base with the bundled sample documents.

Usage:
    python seed.py

Requires GEMINI_API_KEY to be set (embeddings are generated at ingest time).
"""
from __future__ import annotations

from pathlib import Path

from backend import database, ingestion
from backend.config import get_settings

SAMPLES = [
    ("delivery_project_onboarding_sop.md", "delivery", "sop", "Delivery Excellence Office", "internal", "2026-01-15"),
    ("hr_leave_policy.md",                 "hr",       "policy", "HR Operations",           "internal", "2026-04-01"),
    ("engineering_incident_runbook.md",    "engineering", "runbook", "Site Reliability Eng", "internal", "2026-02-10"),
    ("sales_enablement_playbook.md",       "sales",    "playbook", "Sales Enablement",       "restricted", "2026-03-05"),
]


def main() -> None:
    settings = get_settings()
    if not settings.llm_ready:
        raise SystemExit(
            "GEMINI_API_KEY is not set. Add it to .env before seeding "
            "(embeddings need the API)."
        )

    database.init_db()
    base = Path(__file__).parent / "data" / "sample_docs"

    existing = {d["name"] for d in database.list_documents()}
    for fname, dept, dtype, owner, conf, eff in SAMPLES:
        if fname in existing:
            print(f"• {fname} already indexed — skipping")
            continue
        raw = (base / fname).read_bytes()
        meta = {
            "name": fname, "department": dept, "doc_type": dtype,
            "owner": owner, "confidentiality": conf, "effective_date": eff,
        }
        result = ingestion.ingest_document(fname, raw, meta)
        print(f"✓ Indexed {fname}: {result['chunk_count']} chunks")

    print("\nDone. Start the app and try:")
    print("  - What is the leave carry-forward policy?")
    print("  - Steps to respond to a Sev-1 incident")
    print("  - How do I onboard onto a new delivery project?")


if __name__ == "__main__":
    main()
