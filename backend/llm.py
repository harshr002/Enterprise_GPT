"""Google Gemini calls (chat + embeddings) over the REST API via httpx.

Kept provider-specific but tiny. To switch providers, reimplement
`embed_texts`, `embed_query` and `generate_json` / `generate_text`.
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .config import get_settings

# Transient statuses worth retrying (server overloaded / rate-limited).
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3          # total attempts = 1 + retries
_BACKOFF_SECONDS = 1.5    # grows each retry: 1.5s, 3s, 4.5s


class LLMNotConfigured(RuntimeError):
    """Raised when no API key is available."""


class LLMError(RuntimeError):
    """Raised when the LLM provider returns an error (bad key, model, quota…)."""


def _post(client: httpx.Client, url: str, payload: dict) -> dict:
    """POST to Gemini with automatic retry on transient errors.

    A 503/429/500 usually means the model is momentarily overloaded — we wait
    briefly and retry a few times before giving up, so a busy-server blip does
    not surface to the user.
    """
    last_detail = ""
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = client.post(url, json=payload)
        except httpx.HTTPError as e:
            # Network hiccup — retry, then give up.
            last_detail = str(e)
            if attempt < _MAX_RETRIES:
                time.sleep(_BACKOFF_SECONDS * (attempt + 1))
                continue
            raise LLMError(f"Could not reach the AI service: {e}") from e

        if resp.status_code < 400:
            return resp.json()

        # Pull Gemini's own error message out of the response body.
        try:
            last_detail = resp.json().get("error", {}).get("message", "")
        except Exception:
            last_detail = resp.text[:300]

        # Retry transient errors; fail fast on real ones (bad key, bad model).
        if resp.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
            time.sleep(_BACKOFF_SECONDS * (attempt + 1))
            continue

        hint = ""
        if resp.status_code == 404:
            hint = " (the model name may be wrong or unavailable for your key — try GEMINI_CHAT_MODEL=gemini-2.5-flash)"
        elif resp.status_code in (401, 403):
            hint = " (your GEMINI_API_KEY looks invalid or the Generative Language API isn't enabled for it)"
        elif resp.status_code == 429:
            hint = " (you've hit the free-tier rate/quota limit — wait a minute and retry)"
        elif resp.status_code == 503:
            hint = " (the model is temporarily overloaded — retry, or switch GEMINI_CHAT_MODEL to gemini-2.5-flash)"
        raise LLMError(f"AI service error {resp.status_code}: {last_detail}{hint}")

    # Exhausted retries on a transient error.
    raise LLMError(f"AI service busy after {_MAX_RETRIES + 1} attempts: {last_detail}")


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
            data = _post(client, url, payload)
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
        data = _post(client, url, payload)
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
