from __future__ import annotations

import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mock_claimcenter"))
SAMPLES = ROOT / "samples" / "eval" / "files"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("FNOL_SECRETS_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("APP_API_TOKEN", "test-token")
    monkeypatch.setenv("MOCK_CLAIMCENTER_URL", "http://mock-cc")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    for k in ("SEED_COMPOSIO_USER_ID", "AUTO_PUSH", "CONFIDENCE_THRESHOLD"):
        monkeypatch.delenv(k, raising=False)
    from app import db
    from app.config import get_settings

    get_settings.cache_clear()
    db.reset_engine()
    from app.seed import ensure_schema_and_seed

    ensure_schema_and_seed()
    yield
    db.reset_engine()
    get_settings.cache_clear()


@pytest.fixture
def mock_cc(monkeypatch):
    """Route the adapters' httpx clients to the in-process ClaimCenter stand-in."""
    import importlib

    from fastapi.testclient import TestClient

    mock = importlib.import_module("claimcenter_mock")
    mock.CLAIMS.clear()
    mock.CONTACTS.clear()
    mock.TX_SEEN.clear()
    client = TestClient(mock.app, base_url="http://mock-cc")

    class _C:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return client

        def __exit__(self, *a):
            return False

    import app.integrations.guidewire as gw

    monkeypatch.setattr(gw.httpx, "Client", _C)
    return mock


@pytest.fixture
def db():
    from app.db import SessionLocal

    s = SessionLocal()
    yield s
    s.close()
