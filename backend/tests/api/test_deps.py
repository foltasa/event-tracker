from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import current_user_id_middleware
from app.agent.memory import get_current_user_id


def _make_app():
    app = FastAPI()
    app.middleware("http")(current_user_id_middleware)

    @app.get("/whoami")
    def whoami():
        return {"user_id": get_current_user_id()}

    return TestClient(app)


def test_default_user_id_when_header_missing():
    client = _make_app()
    r = client.get("/whoami")
    assert r.json() == {"user_id": "local"}


def test_user_id_from_header():
    client = _make_app()
    r = client.get("/whoami", headers={"X-User-Id": "alice"})
    assert r.json() == {"user_id": "alice"}
