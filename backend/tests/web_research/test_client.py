from unittest.mock import patch, MagicMock

import httpx
import pytest

from app.agent.schemas import ToolError


def _ok_response(payload: dict) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = 200
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


def test_search_returns_hits(monkeypatch):
    monkeypatch.setattr("app.web_research.client.settings.tavily_api_key", "tvly-test")
    monkeypatch.setattr("app.web_research.client.settings.web_search_max_results", 3)

    fake_post = MagicMock(return_value=_ok_response({
        "results": [
            {"url": "https://thalia-theater.de/x", "title": "Spielplan", "content": "Hamlet 19:30"},
            {"url": "https://schauspielhaus.de/y", "title": "Programm", "content": "Faust 20:00"},
        ]
    }))
    with patch("httpx.Client") as ClientCls:
        ClientCls.return_value.__enter__.return_value.post = fake_post
        from app.web_research import client
        hits = client.search("Theater Hamburg 19. Juni")

    assert len(hits) == 2
    assert hits[0]["url"] == "https://thalia-theater.de/x"
    assert hits[0]["title"] == "Spielplan"
    assert hits[0]["content"] == "Hamlet 19:30"

    body = fake_post.call_args.kwargs["json"]
    assert body["query"] == "Theater Hamburg 19. Juni"
    assert body["max_results"] == 3


def test_search_raises_when_key_missing(monkeypatch):
    monkeypatch.setattr("app.web_research.client.settings.tavily_api_key", None)
    from app.web_research import client
    with pytest.raises(ToolError, match="not configured"):
        client.search("anything")


def test_search_wraps_http_errors(monkeypatch):
    monkeypatch.setattr("app.web_research.client.settings.tavily_api_key", "tvly-test")

    bad = MagicMock(spec=httpx.Response)
    bad.status_code = 503
    bad.raise_for_status.side_effect = httpx.HTTPStatusError("503", request=MagicMock(), response=bad)
    with patch("httpx.Client") as ClientCls:
        ClientCls.return_value.__enter__.return_value.post = MagicMock(return_value=bad)
        from app.web_research import client
        with pytest.raises(ToolError, match="unavailable"):
            client.search("x")


def test_extract_returns_text(monkeypatch):
    monkeypatch.setattr("app.web_research.client.settings.tavily_api_key", "tvly-test")
    fake_post = MagicMock(return_value=_ok_response({
        "results": [{"url": "https://thalia-theater.de/x", "raw_content": "Hamlet, 19:30, Großes Haus"}],
        "failed_results": [],
    }))
    with patch("httpx.Client") as ClientCls:
        ClientCls.return_value.__enter__.return_value.post = fake_post
        from app.web_research import client
        text = client.extract("https://thalia-theater.de/x")
    assert "Hamlet" in text


def test_extract_raises_on_failed_result(monkeypatch):
    monkeypatch.setattr("app.web_research.client.settings.tavily_api_key", "tvly-test")
    fake_post = MagicMock(return_value=_ok_response({
        "results": [],
        "failed_results": [{"url": "https://broken/", "error": "404"}],
    }))
    with patch("httpx.Client") as ClientCls:
        ClientCls.return_value.__enter__.return_value.post = fake_post
        from app.web_research import client
        with pytest.raises(ToolError, match="not fetchable"):
            client.extract("https://broken/")
