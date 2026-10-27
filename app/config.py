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
    if os.getenv("APP_ENV", "development").lower() == "production":
        raise RuntimeError(f"{name} must be explicitly configured in production")
    log.warning("%s not set: generated a temporary development value", name)
    return secrets.token_urlsafe(nbytes)


DEMO_ADMIN_PASSWORD = "admin123"
_SEED = os.getenv("SEED_DEMO", "1") == "1"


def _admin_password() -> str:
    supplied = os.getenv("ADMIN_PASSWORD")
    production = os.getenv("APP_ENV", "development").lower() == "production"
    if production:
        if not supplied or supplied == DEMO_ADMIN_PASSWORD or len(supplied) < 14:
            raise RuntimeError("Production requires ADMIN_PASSWORD of at least 14 characters; demo credentials are forbidden")
        if _SEED:
            raise RuntimeError("SEED_DEMO=1 is forbidden in production; set SEED_DEMO=0")
        return supplied
    if supplied:
        return supplied
    if _SEED:  # local-only convenience for the documented demo
        log.warning("Using local demo admin password. Never expose this configuration publicly.")
        return DEMO_ADMIN_PASSWORD
    return _env_or_random("ADMIN_PASSWORD", 18)


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
