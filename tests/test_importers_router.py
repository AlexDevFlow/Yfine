"""Integration tests for /api/imports/* via FastAPI TestClient."""
import os
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YFINE_DATA_DIR", "/tmp/yfine-test-data")
os.makedirs("/tmp/yfine-test-data", exist_ok=True)


@pytest.fixture
def client():
    import models  # noqa: F401 — register all models
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    from database import get_session
    from main import app

    def _override_session():
        with Session(engine) as session:
            yield session

    # Reset the import preview cache between tests so IDs don't leak.
    from services.importers import cache as preview_cache
    preview_cache.clear()

    app.dependency_overrides[get_session] = _override_session

    # Disable CSRF validation for tests by bypassing the middleware logic.
    # Safe-methods still populate the token; state-changing methods skip the check.
    async def _bypass_csrf_dispatch(self, request, call_next):
        import secrets
        token = request.session.get("csrf_token")
        if not token:
            token = secrets.token_hex(32)
            request.session["csrf_token"] = token
        request.state.csrf_token = token
        return await call_next(request)

    with patch("services.importers.undo.get_session_secret", return_value="test-secret-key-123"), \
         patch("csrf.CSRFMiddleware.dispatch", _bypass_csrf_dispatch):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.pop(get_session, None)


def test_formats_endpoint_lists_parsers(client):
    resp = client.get("/api/imports/formats")
    assert resp.status_code == 200
    keys = {f["key"] for f in resp.json()}
    assert {"csv", "ofx", "xlsx"}.issubset(keys)


def test_presets_endpoint_returns_known_presets(client):
    resp = client.get("/api/imports/presets")
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert "revolut" in ids


def test_preview_and_commit_csv_flow(client):
    csv_bytes = (
        b"date,amount,description\n"
        b"2024-01-15,100.00,Salary\n"
        b"2024-01-16,-20.00,Groceries\n"
    )

    resp = client.post(
        "/api/imports/preview",
        files={"file": ("sample.csv", csv_bytes, "text/csv")},
        data={"format": "csv"},
    )
    assert resp.status_code == 200, resp.text
    preview = resp.json()
    assert preview["row_count"] == 2
    assert preview["detected_format"] == "csv"
    assert set(preview["default_include"]) == {0, 1}

    commit_resp = client.post(
        "/api/imports/commit",
        json={
            "preview_id": preview["preview_id"],
            "new_source": {"name": "Test Bank", "currency": "EUR", "starting_balance": 0},
            "include_indices": preview["default_include"],
        },
    )
    assert commit_resp.status_code == 200, commit_resp.text
    body = commit_resp.json()
    assert body["imported"] == 2
    assert body["undo_token"]

    undo_resp = client.request(
        "DELETE",
        "/api/imports/undo",
        json={"undo_token": body["undo_token"]},
    )
    assert undo_resp.status_code == 200
    assert undo_resp.json()["deleted"] == 2


def test_commit_rejects_missing_source(client):
    csv_bytes = (
        b"date,amount,description\n"
        b"2024-01-15,100.00,Salary\n"
    )
    resp = client.post(
        "/api/imports/preview",
        files={"file": ("sample.csv", csv_bytes, "text/csv")},
        data={"format": "csv"},
    )
    preview = resp.json()

    bad = client.post(
        "/api/imports/commit",
        json={"preview_id": preview["preview_id"], "include_indices": [0]},
    )
    assert bad.status_code == 400


def test_commit_rejects_expired_preview(client):
    resp = client.post(
        "/api/imports/commit",
        json={
            "preview_id": "nonexistent-id",
            "source_id": 1,
            "include_indices": [0],
        },
    )
    assert resp.status_code == 410


def test_undo_rejects_invalid_token(client):
    resp = client.request("DELETE", "/api/imports/undo", json={"undo_token": "garbage"})
    assert resp.status_code == 410


def test_preview_auto_detect_csv_without_format(client):
    """Omitting format should still work via extension+content sniffing."""
    csv_bytes = (
        b"date,amount,description\n"
        b"2024-01-15,50.00,Test\n"
    )
    resp = client.post(
        "/api/imports/preview",
        files={"file": ("unknown.csv", csv_bytes, "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json()["detected_format"] == "csv"


def test_preview_detects_revolut_preset(client):
    """Revolut CSV headers trigger preset auto-detection."""
    csv_bytes = (
        b"Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"
        b"TRANSFER,Current,2024-01-10 12:00:00,2024-01-10 12:05:00,Salary,1500.00,0,EUR,COMPLETED,1500.00\n"
    )
    resp = client.post(
        "/api/imports/preview",
        files={"file": ("revolut.csv", csv_bytes, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["detected_preset"] is not None
    assert data["detected_preset"]["id"] == "revolut"
