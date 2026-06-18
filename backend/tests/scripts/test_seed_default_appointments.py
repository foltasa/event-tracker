from datetime import date, datetime, timezone

from app.db.models import Appointment, User
from scripts.seed_default_appointments import seed_turing_college


def test_seed_inserts_45_weekdays(db_session):
    db_session.add(User(id="local", interest_tags=[]))
    db_session.commit()

    n = seed_turing_college(db_session, user_id="local")
    assert n == 45
    rows = db_session.query(Appointment).filter_by(title="Turing College").all()
    assert len(rows) == 45
    # All weekdays only
    for r in rows:
        assert r.day.weekday() < 5
    # Range spans June and July 2026
    assert min(r.day for r in rows) == date(2026, 6, 1)
    assert max(r.day for r in rows) == date(2026, 7, 31)


def test_seed_is_idempotent(db_session):
    db_session.add(User(id="local", interest_tags=[]))
    db_session.commit()
    seed_turing_college(db_session, user_id="local")
    inserted_again = seed_turing_college(db_session, user_id="local")
    assert inserted_again == 0
    assert db_session.query(Appointment).filter_by(title="Turing College").count() == 45


def test_seed_times_anchor_to_hamburg_local(db_session):
    db_session.add(User(id="local", interest_tags=[]))
    db_session.commit()
    seed_turing_college(db_session, user_id="local")
    row = (
        db_session.query(Appointment)
        .filter_by(title="Turing College", day=date(2026, 6, 1))
        .one()
    )
    # Hamburg is UTC+2 in June (CEST). 09:00 local -> 07:00 UTC.
    # SQLite stores datetimes without timezone info, so compare without tzinfo.
    assert row.start_at == datetime(2026, 6, 1, 7, 0)
    # 16:30 local -> 14:30 UTC.
    assert row.end_at == datetime(2026, 6, 1, 14, 30)
