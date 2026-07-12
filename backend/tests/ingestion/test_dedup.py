import pytest

from app.ingestion.dedup import _normalize_venue, _title_jaccard


class TestNormalizeVenue:
    def test_lowercase_and_strip(self):
        assert _normalize_venue("  Laeiszhalle  ") == "laeiszhalle"

    def test_strips_parenthesized_hall_suffix(self):
        assert _normalize_venue("Laeiszhalle (Großer Saal)") == "laeiszhalle"
        assert _normalize_venue("Elbphilharmonie (Kleiner Saal)") == "elbphilharmonie"

    def test_splits_camelcase(self):
        assert _normalize_venue("DeutschesSchauSpielHausHamburg") == "deutsches schau spiel haus hamburg"

    def test_collapses_whitespace_runs(self):
        assert _normalize_venue("Thalia   Theater\tHamburg") == "thalia theater hamburg"

    def test_none_and_empty(self):
        assert _normalize_venue(None) == ""
        assert _normalize_venue("") == ""
        assert _normalize_venue("   ") == ""

    def test_combined_camelcase_and_paren(self):
        assert _normalize_venue("JungesSchauSpielHaus (Malersaal)") == "junges schau spiel haus"


class TestTitleJaccard:
    def test_identical_titles_return_one(self):
        assert _title_jaccard("Hamlet", "Hamlet") == 1.0

    def test_case_insensitive(self):
        assert _title_jaccard("Hamlet", "hamlet") == 1.0

    def test_punctuation_stripped(self):
        assert _title_jaccard("Hamlet!", "Hamlet.") == 1.0

    def test_hamlet_with_subtitle(self):
        # {"hamlet"} vs {"hamlet", "premiere"} -> 1/2
        assert _title_jaccard("Hamlet", "Hamlet (Premiere)") == pytest.approx(0.5)

    def test_disjoint_titles(self):
        assert _title_jaccard("Batman", "Barbie") == 0.0

    def test_none_or_empty(self):
        assert _title_jaccard(None, "Hamlet") == 0.0
        assert _title_jaccard("Hamlet", None) == 0.0
        assert _title_jaccard("", "") == 0.0

    def test_multi_word_overlap(self):
        # {"der", "kirschgarten"} vs {"kirschgarten"} -> 1/2
        assert _title_jaccard("Der Kirschgarten", "Kirschgarten") == pytest.approx(0.5)


from datetime import datetime, timedelta, timezone

from app.db.models import Event
from app.db.models.saved_event import SavedEvent
from app.db.models.user import User
from app.ingestion.dedup import DedupReport, dedup_events


def _make_event(
    session,
    *,
    id_: str,
    external_id: str,
    source: str,
    title: str,
    venue_name: str | None,
    start: datetime,
    description: str = "Description.",
    is_active: bool = True,
    created_at: datetime | None = None,
) -> Event:
    ev = Event(
        id=id_,
        external_id=external_id,
        source=source,
        title=title,
        description=description,
        start_datetime=start,
        venue_name=venue_name,
        category="theater",
        tags=[],
        is_free=False,
        currency="EUR",
        source_url=f"https://x/{id_}",
        raw_data={},
        is_active=is_active,
    )
    if created_at is not None:
        ev.ingested_at = created_at
    session.add(ev)
    session.commit()
    return ev


def _make_user(session, id_: str = "u1") -> User:
    u = User(id=id_)
    session.add(u)
    session.commit()
    return u


_NOW = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)


class TestDedupEvents:
    def test_no_events_no_ops(self, db_session):
        report = dedup_events(db_session)
        assert report == DedupReport(groups_found=0, rows_merged=0, saved_events_migrated=0)

    def test_theater_hamburg_wins_over_ticketmaster(self, db_session):
        _make_event(db_session, id_="tm", external_id="e1", source="ticketmaster",
                    title="Hamlet", venue_name="Laeiszhalle", start=_NOW)
        _make_event(db_session, id_="th", external_id="e2", source="theater_hamburg",
                    title="Hamlet", venue_name="Laeiszhalle (Großer Saal)", start=_NOW)

        report = dedup_events(db_session)
        assert report.rows_merged == 1
        remaining = {e.id for e in db_session.query(Event).all()}
        assert remaining == {"th"}

    def test_saved_events_fk_migrated_before_delete(self, db_session):
        u = _make_user(db_session)
        _make_event(db_session, id_="tm", external_id="e1", source="ticketmaster",
                    title="Hamlet", venue_name="Laeiszhalle", start=_NOW)
        _make_event(db_session, id_="th", external_id="e2", source="theater_hamburg",
                    title="Hamlet", venue_name="Laeiszhalle", start=_NOW)
        db_session.add(SavedEvent(id="s1", user_id=u.id, event_id="tm"))
        db_session.commit()

        dedup_events(db_session)
        remaining_save = db_session.query(SavedEvent).one()
        assert remaining_save.event_id == "th"

    def test_saved_events_double_save_collapses_without_constraint_violation(self, db_session):
        # User saved BOTH the loser (tm) and the winner (th). Migrating the
        # loser's row would collide with the winner's row on the
        # (user_id, event_id) UNIQUE constraint. The loser's row is dropped.
        u = _make_user(db_session)
        _make_event(db_session, id_="tm", external_id="e1", source="ticketmaster",
                    title="Hamlet", venue_name="Laeiszhalle", start=_NOW)
        _make_event(db_session, id_="th", external_id="e2", source="theater_hamburg",
                    title="Hamlet", venue_name="Laeiszhalle", start=_NOW)
        db_session.add_all([
            SavedEvent(id="s_tm", user_id=u.id, event_id="tm"),
            SavedEvent(id="s_th", user_id=u.id, event_id="th"),
        ])
        db_session.commit()

        report = dedup_events(db_session)
        assert report.rows_merged == 1
        remaining = db_session.query(SavedEvent).all()
        assert len(remaining) == 1
        assert remaining[0].event_id == "th"

    def test_title_jaccard_below_threshold_prevents_multi_screen_dedup(self, db_session):
        _make_event(db_session, id_="ev1", external_id="e1", source="theater_hamburg",
                    title="Batman", venue_name="CinemaxX Dammtor", start=_NOW)
        _make_event(db_session, id_="ev2", external_id="e2", source="ticketmaster",
                    title="Barbie", venue_name="CinemaxX Dammtor", start=_NOW)

        report = dedup_events(db_session)
        assert report.rows_merged == 0
        assert {e.id for e in db_session.query(Event).all()} == {"ev1", "ev2"}

    def test_time_tolerance_across_bucket_boundaries(self, db_session):
        _make_event(db_session, id_="a", external_id="e1", source="ticketmaster",
                    title="Hamlet", venue_name="Thalia Theater",
                    start=_NOW.replace(minute=59))
        _make_event(db_session, id_="b", external_id="e2", source="theater_hamburg",
                    title="Hamlet", venue_name="Thalia Theater",
                    start=_NOW.replace(hour=_NOW.hour + 1, minute=0))
        report = dedup_events(db_session)
        assert report.rows_merged == 1

    def test_time_over_tolerance_not_deduped(self, db_session):
        _make_event(db_session, id_="a", external_id="e1", source="ticketmaster",
                    title="Hamlet", venue_name="Thalia Theater", start=_NOW)
        _make_event(db_session, id_="b", external_id="e2", source="theater_hamburg",
                    title="Hamlet", venue_name="Thalia Theater",
                    start=_NOW + timedelta(minutes=90))
        report = dedup_events(db_session)
        assert report.rows_merged == 0

    def test_camelcase_venue_normalization(self, db_session):
        _make_event(db_session, id_="tm", external_id="e1", source="ticketmaster",
                    title="Faust", venue_name="Deutsches Schauspielhaus Hamburg", start=_NOW)
        _make_event(db_session, id_="th", external_id="e2", source="theater_hamburg",
                    title="Faust", venue_name="DeutschesSchauSpielHausHamburg", start=_NOW)
        report = dedup_events(db_session)
        assert report.rows_merged == 1
        assert {e.id for e in db_session.query(Event).all()} == {"th"}

    def test_ties_by_priority_broken_by_older_created_at(self, db_session):
        older = datetime(2026, 6, 1, tzinfo=timezone.utc)
        newer = datetime(2026, 6, 2, tzinfo=timezone.utc)
        _make_event(db_session, id_="old_tm", external_id="e1", source="ticketmaster",
                    title="Hamlet", venue_name="Thalia", start=_NOW, created_at=older)
        _make_event(db_session, id_="new_tm", external_id="e2", source="ticketmaster",
                    title="Hamlet", venue_name="Thalia", start=_NOW, created_at=newer)
        dedup_events(db_session)
        assert {e.id for e in db_session.query(Event).all()} == {"old_tm"}

    def test_idempotent_second_run_is_no_op(self, db_session):
        _make_event(db_session, id_="tm", external_id="e1", source="ticketmaster",
                    title="Hamlet", venue_name="Laeiszhalle", start=_NOW)
        _make_event(db_session, id_="th", external_id="e2", source="theater_hamburg",
                    title="Hamlet", venue_name="Laeiszhalle", start=_NOW)
        first = dedup_events(db_session)
        second = dedup_events(db_session)
        assert first.rows_merged == 1
        assert second.rows_merged == 0

    def test_inactive_events_ignored(self, db_session):
        _make_event(db_session, id_="tm", external_id="e1", source="ticketmaster",
                    title="Hamlet", venue_name="Laeiszhalle", start=_NOW, is_active=False)
        _make_event(db_session, id_="th", external_id="e2", source="theater_hamburg",
                    title="Hamlet", venue_name="Laeiszhalle", start=_NOW)
        report = dedup_events(db_session)
        assert report.rows_merged == 0
