"""All configuration comes from environment variables. No secrets live in code."""
import logging
import os
import secrets
from dataclasses import dataclass, field

log = logging.getLogger("fairshift")

DEMO_ADMIN_PASSWORD = "admin123"
MIN_PROD_ADMIN_PASSWORD_LEN = 14


def _is_production() -> bool:
    return os.getenv("APP_ENV", "development").lower() == "production"


def _seed_demo() -> bool:
    return os.getenv("SEED_DEMO", "1") == "1"


def _env_or_random(name: str, nbytes: int) -> str:
    value = os.getenv(name)
    if value:
        return value
    if _is_production():
        raise RuntimeError(f"{name} must be explicitly configured in production")
    log.warning("%s not set: generated a temporary development value", name)
    return secrets.token_urlsafe(nbytes)


def _admin_password() -> str:
    supplied = os.getenv("ADMIN_PASSWORD")
    if _is_production():
        if not supplied or supplied == DEMO_ADMIN_PASSWORD or len(supplied) < MIN_PROD_ADMIN_PASSWORD_LEN:
            raise RuntimeError(f"Production requires ADMIN_PASSWORD of at least {MIN_PROD_ADMIN_PASSWORD_LEN} "
                               "characters; demo credentials are forbidden")
        if _seed_demo():
            raise RuntimeError("SEED_DEMO=1 is forbidden in production; set SEED_DEMO=0")
        return supplied
    if supplied:
        return supplied
    if _seed_demo():  # local-only convenience for the documented demo
        log.warning("Using local demo admin password. Never expose this configuration publicly.")
        return DEMO_ADMIN_PASSWORD
    return _env_or_random("ADMIN_PASSWORD", 18)


@dataclass(frozen=True)
class Settings:
    db_path: str = field(default_factory=lambda: os.getenv("DB_PATH", "/tmp/fairshift.db"))
    secret_key: str = field(default_factory=lambda: _env_or_random("SECRET_KEY", 32))
    admin_password: str = field(default_factory=_admin_password)
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    tz_offset_min: int = field(default_factory=lambda: int(os.getenv("TZ_OFFSET_MIN", "330")))
    seed_demo: bool = field(default_factory=_seed_demo)


settings = Settings()
