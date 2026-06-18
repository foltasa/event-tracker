from datetime import date, datetime, timezone

from app.db.models import Appointment, User


def test_appointment_minimal_all_day(db_session):
    db_session.add(User(id="local", interest_tags=[]))
    db_session.add(Appointment(
        id="a1", user_id="local", title="Birthday",
        day=date(2026, 6, 16), start_at=None, end_at=None,
    ))
    db_session.commit()
    row = db_session.query(Appointment).one()
    assert row.title == "Birthday"
    assert row.day == date(2026, 6, 16)
    assert row.start_at is None
    assert row.end_at is None
    assert row.created_at is not None


def test_appointment_timed(db_session):
    db_session.add(User(id="local", interest_tags=[]))
    db_session.add(Appointment(
        id="a2", user_id="local", title="Standup",
        day=date(2026, 6, 16),
        start_at=datetime(2026, 6, 16, 9, 0, tzinfo=timezone.utc),
        end_at=datetime(2026, 6, 16, 9, 30, tzinfo=timezone.utc),
    ))
    db_session.commit()
    row = db_session.query(Appointment).one()
    assert row.start_at.hour == 9
    assert row.end_at.minute == 30
