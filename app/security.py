"""PIN hashing, HMAC-signed bearer tokens and a login throttle (stdlib only)."""
import base64
import hashlib
import hmac
import json
import os
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import Header, HTTPException

from .config import settings

PBKDF2_ITERATIONS = 120_000
TOKEN_TTL_S = 12 * 3600


def _pbkdf2(pin: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PBKDF2_ITERATIONS)


def hash_pin(pin: str) -> str:
    salt = os.urandom(16)
    return f"{salt.hex()}${_pbkdf2(pin, salt).hex()}"


_DUMMY = hash_pin("dummy-not-a-real-pin")  # burns equal CPU for unknown users (no user enumeration by timing)


def verify_pin(pin: str, stored: str | None) -> bool:
    salt_hex, dk_hex = (stored or _DUMMY).split("$")
    matches = hmac.compare_digest(_pbkdf2(pin, bytes.fromhex(salt_hex)), bytes.fromhex(dk_hex))
    return matches and stored is not None


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sig(payload: str) -> str:
    return _b64(hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).digest())


def make_token(sub: int, role: str, ttl: int = TOKEN_TTL_S) -> str:
    payload = _b64(json.dumps({"sub": sub, "role": role, "exp": int(time.time()) + ttl}).encode())
    return f"{payload}.{_sig(payload)}"


def read_token(token: str) -> dict | None:
    try:
        payload, sig = token.split(".")
        if not hmac.compare_digest(sig, _sig(payload)):
            return None
        data = json.loads(_unb64(payload))
        return data if data["exp"] > time.time() else None
    except (ValueError, KeyError, TypeError):  # malformed token: bad split/base64/JSON/shape
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


class LoginThrottle:
    """Sliding-window limiter for failed logins.

    Thread-safe and memory-bounded: expired entries are dropped on access and the whole table is
    swept when it grows past `max_keys`, so a stream of one-off keys cannot leak memory.
    State is per process; use a shared store (e.g. Redis) when running several instances.
    """

    def __init__(self, limit: int = 5, window_s: float = 60.0, max_keys: int = 10_000,
                 clock: Callable[[], float] = time.monotonic):
        self._limit, self._window, self._max_keys, self._clock = limit, window_s, max_keys, clock
        self._fails: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._fails)

    def _live(self, key: str, now: float) -> deque[float]:
        q = self._fails.get(key)
        if q is None:
            return deque()
        while q and now - q[0] >= self._window:
            q.popleft()
        if not q:
            del self._fails[key]
        return q

    def check(self, key: str) -> None:
        with self._lock:
            if len(self._live(key, self._clock())) >= self._limit:
                raise HTTPException(429, "Too many attempts. Wait a minute.")

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            if len(self._fails) >= self._max_keys:
                for k in list(self._fails):
                    self._live(k, now)
            self._fails.setdefault(key, deque()).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


login_throttle = LoginThrottle()
