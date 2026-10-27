import os
import tempfile

_dir = tempfile.mkdtemp()
os.environ.update(DB_PATH=f"{_dir}/t.db", SECRET_KEY="test-secret", ADMIN_PASSWORD="admin-pass",
                  GEMINI_API_KEY="", SEED_DEMO="1")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


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
