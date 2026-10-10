import os
import sys
import tempfile
from pathlib import Path

# Must be set before the app package is imported (settings load at import time).
_TMP = Path(tempfile.mkdtemp(prefix="aiyt_v2_test_"))
os.environ["DATA_DIR"] = str(_TMP / "data")
os.environ["APP_PASSWORD"] = "test-password-123"
os.environ["SESSION_SECRET"] = "test-session-secret-0123456789"
os.environ["FRONTEND_DIST"] = str(_TMP / "no-dist")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return Path(os.environ["DATA_DIR"])


@pytest.fixture()
def client():
    auth.reset_rate_limit()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def authed(client):
    r = client.post("/api/auth/login", json={"password": os.environ["APP_PASSWORD"]})
    assert r.status_code == 200, r.text
    return client


def pytest_configure(config):
    config.addinivalue_line("markers", "network: needs internet but no key")
    config.addinivalue_line("markers", "needs_key: needs a real provider key (owner adds on Settings page)")
