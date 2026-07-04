from datetime import datetime, timezone

from app.db.models.event import Event, visible_events_filter


def _make(session, **overrides):
    base = dict(
        id="e0",
        external_id="ext0",
        source="ticketmaster",
        title="T",
        description="A real description.",
        start_datetime=datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc),
        category="concerts",
        tags=[],
        source_url="https://x/e",
        raw_data={},
    )
    base.update(overrides)
    ev = Event(**base)
    session.add(ev)
    session.commit()
    return ev


def test_filter_returns_only_active_with_description_when_toggle_on(db_session, monkeypatch):
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "hide_events_without_description", True)

    _make(db_session, id="ok",       description="Real text.",  is_active=True)
    _make(db_session, id="empty",    description="",            is_active=True, external_id="e2")
    _make(db_session, id="null",     description=None,          is_active=True, external_id="e3")
    _make(db_session, id="inactive", description="Real text.",  is_active=False, external_id="e4")

    ids = {r.id for r in db_session.query(Event).filter(visible_events_filter()).all()}
    assert ids == {"ok"}


def test_filter_ignores_description_when_toggle_off(db_session, monkeypatch):
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "hide_events_without_description", False)

    _make(db_session, id="ok",       description="Real text.",  is_active=True)
    _make(db_session, id="empty",    description="",            is_active=True, external_id="e2")
    _make(db_session, id="null",     description=None,          is_active=True, external_id="e3")
    _make(db_session, id="inactive", description="Real text.",  is_active=False, external_id="e4")

    ids = {r.id for r in db_session.query(Event).filter(visible_events_filter()).all()}
    # Active without desc are visible; inactive still hidden.
    assert ids == {"ok", "empty", "null"}


def test_filter_composes_with_other_filters(db_session, monkeypatch):
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "hide_events_without_description", True)

    _make(db_session, id="concerts", category="concerts", description="A")
    _make(db_session, id="theater", category="theater", description="B", external_id="e2")
    _make(db_session, id="concerts_empty", category="concerts", description="", external_id="e3")

    ids = {
        r.id
        for r in db_session.query(Event)
        .filter(visible_events_filter())
        .filter(Event.category == "concerts")
        .all()
    }
    assert ids == {"concerts"}
