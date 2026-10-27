import os
import tempfile

_dir = tempfile.mkdtemp()
os.environ.update(DB_PATH=f"{_dir}/t.db", SECRET_KEY="test-secret", ADMIN_PASSWORD="admin-pass",
                  GEMINI_API_KEY="", SEED_DEMO="1")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_workforce_cache():
    """Workforce analytics are cached for a few seconds in production; tests must not see each other's data."""
    from app.services import workforce
    workforce.clear_cache()
    yield


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def _hdr(client, url, body):
    r = client.post(url, json=body)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def admin(client):
    return _hdr(client, "/api/auth/admin", {"password": "admin-pass"})


@pytest.fixture()
def worker(client):
    return _hdr(client, "/api/auth/worker", {"code": "FAC01", "pin": "1234"})
