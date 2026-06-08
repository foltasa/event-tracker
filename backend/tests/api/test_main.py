from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with patch("app.main.create_scheduler") as mock_sched:
        mock_sched.return_value = MagicMock()
        with TestClient(app) as c:
            yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


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
    with patch("app.main.create_scheduler", return_value=mock_scheduler):
        with TestClient(app):
            mock_scheduler.start.assert_called_once()
        mock_scheduler.shutdown.assert_called_once_with(wait=False)
