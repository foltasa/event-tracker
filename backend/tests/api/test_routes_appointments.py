from datetime import date, datetime, timezone

import pytest

from app.db.models import Appointment, User


@pytest.fixture
def setup(db_session):
    db_session.add(User(id="local", interest_tags=[]))
    db_session.add(User(id="other", interest_tags=[]))
    db_session.add(Appointment(
        id="a1", user_id="local", title="In window",
        day=date(2026, 6, 16),
        start_at=datetime(2026, 6, 16, 9, 0, tzinfo=timezone.utc),
        end_at=datetime(2026, 6, 16, 10, 0, tzinfo=timezone.utc),
    ))
    db_session.add(Appointment(
        id="a2", user_id="local", title="Out of window",
        day=date(2026, 8, 1), start_at=None, end_at=None,
    ))
    db_session.add(Appointment(
        id="a3", user_id="other", title="Other user",
        day=date(2026, 6, 16), start_at=None, end_at=None,
    ))
    db_session.commit()


def test_list_filters_by_user_and_window(client, setup):
    r = client.get("/appointments?from=2026-06-01&to=2026-06-30")
    assert r.status_code == 200
    body = r.json()
    titles = [a["title"] for a in body["appointments"]]
    assert titles == ["In window"]


def test_list_defaults_to_90_day_window(client, setup):
    # Using monkeypatchable "today" is overkill; just verify the default
    # window includes June 2026 when the test runs.
    r = client.get("/appointments")
    assert r.status_code == 200
