"""Authentication & access control (RBAC).

Deliberately dependency-free: passwords are hashed with PBKDF2 (stdlib
hashlib) and session tokens are compact HMAC-signed tokens (stdlib hmac) —
so nothing here needs a native build and it deploys anywhere.

Roles
-----
- "admin"    : manages documents, sees every department + restricted content,
               views analytics and users.
- "employee" : can ask questions; retrieval is scoped to their own department
               (plus shared "general") and excludes "restricted" documents.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Optional

from fastapi import Header, HTTPException

from . import database

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production-please").encode()
TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_SECONDS", str(60 * 60 * 12)))  # 12h


# --------------------------------------------------------------------------
# Password hashing (PBKDF2-HMAC-SHA256)
# --------------------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"{salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split("$", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000)
    return hmac.compare_digest(dk.hex(), hash_hex)


# --------------------------------------------------------------------------
# Signed tokens (a small self-contained JWT-style token)
# --------------------------------------------------------------------------
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def create_token(user_id: str) -> str:
    payload = {"sub": user_id, "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    body = _b64(json.dumps(payload).encode())
    sig = _b64(hmac.new(SECRET_KEY, body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: str) -> Optional[str]:
    """Return the user id if the token is valid and unexpired, else None."""
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = _b64(hmac.new(SECRET_KEY, body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_unb64(body))
    except Exception:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload.get("sub")


# --------------------------------------------------------------------------
# User operations
# --------------------------------------------------------------------------
def register_user(email: str, password: str, name: str,
                  department: str = "general", role: str = "employee") -> dict[str, Any]:
    email = email.strip().lower()
    if not email or not password:
        raise ValueError("Email and password are required.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    if database.get_user_by_email(email):
        raise ValueError("An account with this email already exists.")
    user = database.create_user(
        email=email, name=name or email.split("@")[0],
        password_hash=hash_password(password),
        role=role, department=department or "general",
    )
    return _public(user)


def authenticate(email: str, password: str) -> dict[str, Any]:
    user = database.get_user_by_email(email.strip().lower())
    if not user or not verify_password(password, user["password_hash"]):
        raise ValueError("Invalid email or password.")
    return user


def _public(user: dict[str, Any]) -> dict[str, Any]:
    """User object safe to send to the client (no password hash)."""
    return {
        "id": user["id"], "email": user["email"], "name": user["name"],
        "role": user["role"], "department": user["department"],
    }


# --------------------------------------------------------------------------
# FastAPI dependencies
# --------------------------------------------------------------------------
def current_user(authorization: Optional[str] = Header(None)) -> dict[str, Any]:
    """Resolve the logged-in user from the Authorization: Bearer <token> header."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated. Please log in.")
    token = authorization.split(" ", 1)[1].strip()
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Session expired or invalid. Please log in again.")
    user = database.get_user_by_id(user_id)
    if not user:
        raise HTTPException(401, "Account no longer exists.")
    return user


def require_admin(user: dict[str, Any]) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(403, "This action requires an administrator account.")
    return user


# --------------------------------------------------------------------------
# Access control: what documents may a user retrieve?
# --------------------------------------------------------------------------
def visibility_for(user: dict[str, Any], requested_department: str = "all") -> dict[str, Any]:
    """Compute the retrieval filter for a user.

    Returns {"departments": list|None, "confidentialities": list|None}.
    None means "no restriction" (admins).
    """
    if user.get("role") == "admin":
        # Admin sees everything; may narrow by the department dropdown.
        if requested_department in ("all", "", None):
            return {"departments": None, "confidentialities": None}
        return {"departments": [requested_department, "general"], "confidentialities": None}

    # Employees: only their department + shared, and never "restricted".
    return {
        "departments": [user.get("department", "general"), "general"],
        "confidentialities": ["public", "internal"],
    }


# --------------------------------------------------------------------------
# Seed default accounts (so the app is usable immediately)
# --------------------------------------------------------------------------
def seed_default_users() -> None:
    """Create demo accounts once, if no users exist yet."""
    if database.count_users() > 0:
        return
    admin_email = os.getenv("ADMIN_EMAIL", "admin@demo.com").lower()
    admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
    database.create_user(
        email=admin_email, name="Admin User",
        password_hash=hash_password(admin_password),
        role="admin", department="all",
    )
    # A couple of demo employees to show department-scoped access.
    for email, dept in [("hr@demo.com", "hr"), ("engineer@demo.com", "engineering")]:
        database.create_user(
            email=email, name=email.split("@")[0].upper(),
            password_hash=hash_password("password123"),
            role="employee", department=dept,
        )
