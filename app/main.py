import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import settings
from .db import connect, init_db
from .services.seed import DEMO_PIN, seed

STATIC = Path(__file__).with_name("static")
log = logging.getLogger("fairshift")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if settings.seed_demo:
        conn = connect()
        try:
            seed(conn)
        finally:
            conn.close()
        log.warning("Demo data loaded. Worker logins CON01/FAC01/HOS01 with PIN %s. Disable with SEED_DEMO=0.", DEMO_PIN)
    yield


app = FastAPI(title="FairShift", version="1.0", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=1024)  # JS/CSS/HTML and JSON compress well; helps slow mobile links
app.include_router(router)

CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'")
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(self), microphone=(self), geolocation=(self)",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    path = request.url.path
    if not path.startswith("/api/docs"):  # Swagger UI needs inline scripts and a CDN
        resp.headers["Content-Security-Policy"] = CSP
    if not path.startswith("/api"):
        resp.headers["Cache-Control"] = "no-cache"
    resp.headers.update(SECURITY_HEADERS)
    return resp


@app.get("/healthz")
def healthz():
    """Liveness probe: confirms the ASGI process is responding."""
    return {"ok": True}


@app.get("/readyz")
def readyz():
    """Readiness probe: verifies the configured database is reachable."""
    conn = connect()
    try:
        conn.execute("SELECT 1").fetchone()
    except Exception:
        log.exception("Readiness check failed")
        raise HTTPException(status_code=503, detail="Service not ready")
    finally:
        conn.close()
    return {"ready": True}


@app.get("/", include_in_schema=False)
def landing():
    return FileResponse(STATIC / "index.html")


@app.get("/worker", include_in_schema=False)
def worker_app():
    return FileResponse(STATIC / "worker.html")


@app.get("/admin", include_in_schema=False)
def admin_app():
    return FileResponse(STATIC / "admin.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
