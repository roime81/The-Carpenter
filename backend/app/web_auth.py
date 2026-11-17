from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from app.config import settings


SESSION_TTL_SECONDS = 12 * 60 * 60
COOKIE_NAME = "carpenter_auth"
_ALLOWED_ROLES = {"viewer", "operator", "admin"}


def authenticate_token(token: str) -> dict[str, str] | None:
    """Resolve a configured web credential to its least-privileged role."""
    if not token:
        return None
    credentials = (
        ("admin", getattr(settings, "admin_token", "")),
        ("operator", getattr(settings, "operator_token", "")),
        ("viewer", getattr(settings, "viewer_token", "")),
    )
    matched_role: str | None = None
    candidate = token.encode("utf-8")
    # Compare every configured credential rather than returning on the first match.
    for role, expected in credentials:
        expected_bytes = (expected or "").encode("utf-8")
        matched = bool(expected_bytes) and hmac.compare_digest(candidate, expected_bytes)
        if matched and matched_role is None:
            matched_role = role
    if matched_role is None:
        return None
    return {"subject": f"web-{matched_role}", "role": matched_role}


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(payload: str) -> str:
    secret = getattr(settings, "session_secret", "") or getattr(settings, "admin_token", "")
    if not secret:
        raise RuntimeError("A session-signing secret is required.")
    digest = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(digest)


def issue_session(token: str, now: int | None = None) -> tuple[dict[str, Any], str] | None:
    identity = authenticate_token(token)
    if identity is None:
        return None
    issued_at = int(time.time() if now is None else now)
    claims: dict[str, Any] = {
        **identity,
        "iat": issued_at,
        "exp": issued_at + SESSION_TTL_SECONDS,
        "csrf": secrets.token_urlsafe(32),
        "nonce": secrets.token_urlsafe(16),
    }
    encoded = _b64encode(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    value = f"{encoded}.{_sign(encoded)}"
    return claims, value


def read_session(cookie_value: str | None, now: int | None = None) -> dict[str, Any] | None:
    if not cookie_value or "." not in cookie_value:
        return None
    encoded, supplied_signature = cookie_value.rsplit(".", 1)
    try:
        expected_signature = _sign(encoded)
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        claims = json.loads(_b64decode(encoded))
        if not isinstance(claims, dict):
            return None
        current = int(time.time() if now is None else now)
        if claims.get("role") not in _ALLOWED_ROLES:
            return None
        if not isinstance(claims.get("subject"), str) or not claims["subject"]:
            return None
        if not isinstance(claims.get("csrf"), str) or len(claims["csrf"]) < 32:
            return None
        issued_at = int(claims.get("iat", 0))
        expires_at = int(claims.get("exp", 0))
        if issued_at > current + 60 or expires_at <= current:
            return None
        if expires_at - issued_at > SESSION_TTL_SECONDS:
            return None
        return claims
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def verify_csrf(identity: dict[str, Any], supplied: str) -> bool:
    expected = identity.get("csrf", "")
    if not isinstance(expected, str) or not expected or not supplied:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), supplied.encode("utf-8"))
