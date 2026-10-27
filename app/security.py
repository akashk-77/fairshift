"""PIN hashing + HMAC-signed bearer tokens (stdlib only)."""
import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import Header, HTTPException

from .config import settings


def hash_pin(pin: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 120_000)
    return f"{salt.hex()}${dk.hex()}"


_DUMMY = hash_pin("dummy-not-a-real-pin")


def verify_pin(pin: str, stored: str | None) -> bool:
    salt_hex, dk_hex = (stored or _DUMMY).split("$")
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt_hex), 120_000)
    return hmac.compare_digest(dk.hex(), dk_hex) and stored is not None


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sig(payload: str) -> str:
    return _b64(hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).digest())


def make_token(sub: int, role: str, ttl: int = 12 * 3600) -> str:
    payload = _b64(json.dumps({"sub": sub, "role": role, "exp": int(time.time()) + ttl}).encode())
    return f"{payload}.{_sig(payload)}"


def read_token(token: str) -> dict | None:
    try:
        payload, sig = token.split(".")
        if not hmac.compare_digest(sig, _sig(payload)):
            return None
        data = json.loads(_unb64(payload))
        return data if data["exp"] > time.time() else None
    except Exception:
        return None


def _bearer(authorization: str | None, role: str) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Login required")
    data = read_token(authorization[7:])
    if not data or data.get("role") != role:
        raise HTTPException(401, "Session expired or not allowed")
    return data


def worker_claims(authorization: str | None = Header(None)) -> dict:
    return _bearer(authorization, "worker")


def admin_claims(authorization: str | None = Header(None)) -> dict:
    return _bearer(authorization, "admin")
