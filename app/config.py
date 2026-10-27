"""All configuration comes from environment variables. No secrets live in code."""
import logging
import os
import secrets
from dataclasses import dataclass, field

log = logging.getLogger("fairshift")


def _env_or_random(name: str, nbytes: int) -> str:
    v = os.getenv(name)
    if v:
        return v
    log.warning("%s not set: generated a temporary value (set it via Secret Manager in production)", name)
    return secrets.token_urlsafe(nbytes)


DEMO_ADMIN_PASSWORD = "admin123"
_SEED = os.getenv("SEED_DEMO", "1") == "1"


def _admin_password() -> str:
    if os.getenv("ADMIN_PASSWORD"):
        return os.environ["ADMIN_PASSWORD"]
    if _SEED:  # demo mode: documented default so judges/teammates can log in
        log.warning("ADMIN_PASSWORD not set: using demo password '%s'. Set ADMIN_PASSWORD for real use.", DEMO_ADMIN_PASSWORD)
        return DEMO_ADMIN_PASSWORD
    return _env_or_random("ADMIN_PASSWORD", 9)


@dataclass(frozen=True)
class Settings:
    db_path: str = field(default_factory=lambda: os.getenv("DB_PATH", "/tmp/fairshift.db"))
    secret_key: str = field(default_factory=lambda: _env_or_random("SECRET_KEY", 32))
    admin_password: str = field(default_factory=_admin_password)
    admin_is_demo: bool = field(default_factory=lambda: _SEED and not os.getenv("ADMIN_PASSWORD"))
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    tz_offset_min: int = field(default_factory=lambda: int(os.getenv("TZ_OFFSET_MIN", "330")))
    seed_demo: bool = field(default_factory=lambda: os.getenv("SEED_DEMO", "1") == "1")


settings = Settings()
