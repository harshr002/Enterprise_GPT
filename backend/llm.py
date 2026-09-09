"""Google Gemini calls (chat + embeddings) over the REST API via httpx.

Kept provider-specific but tiny. To switch providers, reimplement
`embed_texts`, `embed_query` and `generate_json` / `generate_text`.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from .config import get_settings


class LLMNotConfigured(RuntimeError):
    """Raised when no API key is available."""


def _require_key() -> str:
    s = get_settings()
    if not s.llm_ready:
        raise LLMNotConfigured(
            "GEMINI_API_KEY is not set. Add it to your .env file "
            "(get a free key at https://aistudio.google.com/app/apikey)."
        )
    return s.gemini_api_key


# --------------------------------------------------------------------------
# Embeddings
# --------------------------------------------------------------------------
def embed_texts(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """Embed a batch of texts. Returns one vector per text."""
    s = get_settings()
    key = _require_key()
    url = f"{s.gemini_base}/models/{s.embed_model}:embedContent?key={key}"
    vectors: list[list[float]] = []
    # Gemini's embedContent takes one content at a time; loop (batched httpx).
    with httpx.Client(timeout=60) as client:
        for text in texts:
            payload = {
                "model": f"models/{s.embed_model}",
                "content": {"parts": [{"text": text[:8000]}]},
                "taskType": task_type,
            }
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            vectors.append(data["embedding"]["values"])
    return vectors


def embed_query(text: str) -> list[float]:
    return embed_texts([text], task_type="RETRIEVAL_QUERY")[0]


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------
def _generate(prompt: str, *, json_mode: bool, temperature: float = 0.2) -> str:
    s = get_settings()
    key = _require_key()
    url = f"{s.gemini_base}/models/{s.chat_model}:generateContent?key={key}"
    gen_config: dict[str, Any] = {"temperature": temperature}
    if json_mode:
        gen_config["responseMimeType"] = "application/json"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": gen_config,
    }
    with httpx.Client(timeout=90) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        # Safety blocks or empty candidates.
        return ""


def generate_text(prompt: str, temperature: float = 0.3) -> str:
    return _generate(prompt, json_mode=False, temperature=temperature)


def generate_json(prompt: str, temperature: float = 0.2) -> dict[str, Any]:
    raw = _generate(prompt, json_mode=True, temperature=temperature)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Best-effort: pull the first {...} block.
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {}
