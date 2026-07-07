import httpx

from app.ingestion.eventim import RetryStats, get_json_with_retry


class _FakeClient:
    def __init__(self, responses: list[tuple[int, str]]):
        self._responses = list(responses)
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        status, body = self._responses.pop(0) if self._responses else (200, "{}")
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))


def test_returns_json_on_first_success():
    stats = RetryStats()
    client = _FakeClient(responses=[(200, '{"totalPages": 3, "products": []}')])
    body = get_json_with_retry(client, "https://example.com/x", params={}, stats=stats, sleep_fn=lambda _s: None)
    assert body == {"totalPages": 3, "products": []}
    assert stats.total_retries == 0


def test_retries_on_403_then_succeeds():
    stats = RetryStats()
    sleeps: list[float] = []
    client = _FakeClient(responses=[(403, ""), (200, '{"ok": true}')])
    body = get_json_with_retry(client, "https://example.com/x", params={}, stats=stats, sleep_fn=sleeps.append)
    assert body == {"ok": True}
    assert client.calls == 2
    assert stats.total_retries == 1
    assert stats.akamai_403s == 1
    assert sleeps == [2.0]


def test_retries_on_429_and_503_mixed():
    stats = RetryStats()
    sleeps: list[float] = []
    client = _FakeClient(responses=[(429, ""), (503, ""), (200, '{"ok": true}')])
    body = get_json_with_retry(client, "https://example.com/x", params={}, stats=stats, sleep_fn=sleeps.append)
    assert body == {"ok": True}
    assert stats.total_retries == 2
    assert sleeps == [2.0, 4.0]


def test_exhausted_after_four_attempts():
    stats = RetryStats()
    client = _FakeClient(responses=[(403, ""), (403, ""), (403, ""), (403, "")])
    body = get_json_with_retry(client, "https://example.com/x", params={}, stats=stats, sleep_fn=lambda _s: None)
    assert body is None
    assert client.calls == 4
    assert stats.total_retries == 4
    assert stats.exhausted == 1
    assert stats.akamai_403s == 4


def test_non_retry_status_returns_none_without_retry():
    stats = RetryStats()
    client = _FakeClient(responses=[(404, "")])
    body = get_json_with_retry(client, "https://example.com/x", params={}, stats=stats, sleep_fn=lambda _s: None)
    assert body is None
    assert client.calls == 1
    assert stats.total_retries == 0


def test_akamai_reference_captured_from_403_body():
    stats = RetryStats()
    body_403 = "<html>Access Denied. Reference #18.abcd1234.1720350000.deadbeef</html>"
    client = _FakeClient(responses=[(403, body_403), (200, '{"ok": true}')])
    get_json_with_retry(client, "https://example.com/x", params={}, stats=stats, sleep_fn=lambda _s: None)
    assert stats.akamai_refs == ["18.abcd1234.1720350000.deadbeef"]


def test_akamai_refs_capped_at_five():
    stats = RetryStats()
    body_403 = "<html>Ref #aa.bb.cc.dd</html>"
    client = _FakeClient(responses=[(403, body_403)] * 6)
    for _ in range(2):
        get_json_with_retry(client, "https://example.com/x", params={}, stats=stats, sleep_fn=lambda _s: None)
    assert len(stats.akamai_refs) <= 5


def test_json_get_passes_params():
    """Verify params argument is forwarded to the client."""
    stats = RetryStats()
    captured = {}

    class _Capture:
        def get(self, url, **kwargs):
            captured["url"] = url
            captured["params"] = kwargs.get("params")
            return httpx.Response(200, text="{}", request=httpx.Request("GET", url))

    get_json_with_retry(_Capture(), "https://example.com/x", params={"page": 2, "top": 50}, stats=stats, sleep_fn=lambda _s: None)
    assert captured["params"] == {"page": 2, "top": 50}
