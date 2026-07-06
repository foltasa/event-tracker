import httpx

from app.ingestion.scrapers.ohschonhell import RetryStats, get_with_retry


class _FakeClient:
    def __init__(self, statuses: list[int], body: str = "<html></html>"):
        self._statuses = list(statuses)
        self._body = body
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        status = self._statuses.pop(0) if self._statuses else 200
        return httpx.Response(status, text=self._body, request=httpx.Request("GET", url))


def test_returns_body_on_first_success():
    stats = RetryStats()
    client = _FakeClient(statuses=[200])
    body = get_with_retry(client, "https://example.com/x", stats=stats, sleep_fn=lambda _s: None)
    assert body == "<html></html>"
    assert stats.total_retries == 0


def test_retries_on_429_then_succeeds():
    stats = RetryStats()
    sleeps: list[float] = []
    client = _FakeClient(statuses=[429, 200])
    body = get_with_retry(client, "https://example.com/x", stats=stats, sleep_fn=sleeps.append)
    assert body is not None
    assert client.calls == 2
    assert stats.total_retries == 1
    assert sleeps == [1.0]


def test_retries_up_to_three_attempts_then_gives_up():
    stats = RetryStats()
    sleeps: list[float] = []
    client = _FakeClient(statuses=[429, 503, 429])
    body = get_with_retry(client, "https://example.com/x", stats=stats, sleep_fn=sleeps.append)
    assert body is None
    assert client.calls == 3
    assert stats.total_retries == 3
    assert stats.exhausted == 1
    assert sleeps == [1.0, 2.0]  # sleeps before attempts 2 and 3; no sleep after final


def test_non_retry_status_returns_none_without_retry():
    stats = RetryStats()
    sleeps: list[float] = []
    client = _FakeClient(statuses=[404])
    body = get_with_retry(client, "https://example.com/x", stats=stats, sleep_fn=sleeps.append)
    assert body is None
    assert client.calls == 1
    assert sleeps == []
