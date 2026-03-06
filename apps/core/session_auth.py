from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    pad = "=" * ((4 - (len(raw) % 4)) % 4)
    return base64.urlsafe_b64decode((raw + pad).encode("utf-8"))


def create_session_token(*, username: str, secret: str, ttl_seconds: int, role: str = "viewer") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=max(60, ttl_seconds))).timestamp()),
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_session_token(token: str, *, secret: str) -> dict | None:
    try:
        payload_b64, signature = token.split(".", 1)
    except ValueError:
        return None

    expected = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    sub = payload.get("sub")
    exp = payload.get("exp")
    if not sub or not isinstance(exp, int):
        return None
    if exp <= int(datetime.now(timezone.utc).timestamp()):
        return None
    return payload
