from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.models import User
from app.main import _ensure_default_user, app


@pytest.fixture
def client():
    with patch("app.main.create_scheduler") as mock_sched, \
         patch("app.main.run_migrations"), \
         patch("app.main._ensure_default_user"):
        mock_sched.return_value = MagicMock()
        with TestClient(app) as c:
            yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_cors_preflight_allows_localhost_dev_origin(client):
    resp = client.options(
        "/digest",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-user-id,content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "GET" in resp.headers.get("access-control-allow-methods", "")


def test_ingestion_run_returns_report(client):
    mock_report = MagicMock(inserted=3, updated=1, skipped=0)
    with patch("app.main.run_ingestion", return_value=mock_report):
        resp = client.post("/ingestion/run")
    assert resp.status_code == 200
    assert resp.json() == {"inserted": 3, "updated": 1, "skipped": 0}


def test_ingestion_run_returns_500_on_failure(client):
    with patch("app.main.run_ingestion", side_effect=RuntimeError("db down")):
        resp = client.post("/ingestion/run")
    assert resp.status_code == 500
    assert resp.json().get("detail") == "Ingestion failed"


def test_lifespan_starts_and_stops_scheduler():
    mock_scheduler = MagicMock()
    with patch("app.main.create_scheduler", return_value=mock_scheduler), \
         patch("app.main.run_migrations"), \
         patch("app.main._ensure_default_user"):
        with TestClient(app):
            mock_scheduler.start.assert_called_once()
        mock_scheduler.shutdown.assert_called_once_with(wait=False)


def test_ensure_default_user_creates_when_missing(db_session, monkeypatch):
    monkeypatch.setattr("app.main.settings.default_user_id", "local")
    monkeypatch.setattr("app.main.SessionLocal", lambda: _ContextSession(db_session))

    _ensure_default_user()

    user = db_session.query(User).filter_by(id="local").one()
    assert user.city == "Hamburg"
    assert user.interest_tags == []


def test_ensure_default_user_idempotent(db_session, monkeypatch):
    monkeypatch.setattr("app.main.settings.default_user_id", "local")
    monkeypatch.setattr("app.main.SessionLocal", lambda: _ContextSession(db_session))
    db_session.add(User(id="local", about_me="already here"))
    db_session.commit()

    _ensure_default_user()

    users = db_session.query(User).filter_by(id="local").all()
    assert len(users) == 1
    assert users[0].about_me == "already here"


class _ContextSession:
    """Wrap an existing Session so `with SessionLocal() as db` doesn't close it."""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *_exc):
        return False
