import logging

from app.ingestion.logging_util import IngestionFormatter


def _make_record(level: int, event: str, body: dict) -> logging.LogRecord:
    rec = logging.LogRecord(
        name="test", level=level, pathname=__file__, lineno=1,
        msg="", args=(), exc_info=None,
    )
    rec.event = event
    rec.body = body
    # Fixed timestamp so tests are deterministic.
    rec.created = 1_781_308_801.0  # 2026-06-13 04:00:01 UTC-ish; formatter uses localtime
    return rec


def test_formatter_pads_columns_for_run_start():
    fmt = IngestionFormatter()
    rec = _make_record(logging.INFO, "run.start", {"run": "a3f2", "sources": 5})
    line = fmt.format(rec)
    # Positional layout: TS(19) SP LVL(5) SP EVENT(20) SP BODY
    assert line[0:10].count("-") == 2         # YYYY-MM-DD
    assert line[10] == " "
    assert line[19] == " "
    assert line[20:25] == "INFO "             # level column ljust(5)
    assert line[25] == " "
    assert line[26:35] == "run.start"         # event name
    assert line[35:46] == " " * 11            # padding to 20 chars
    assert line[46] == " "
    assert line[47:] == "run=a3f2 sources=5"


def test_formatter_renders_adapter_tag_first():
    fmt = IngestionFormatter()
    rec = _make_record(logging.INFO, "fetch.start", {"adapter": "ticketmaster"})
    line = fmt.format(rec)
    # fetch.start (11 chars) padded to 20 + 1 separator = 10 spaces before body.
    assert line.endswith("fetch.start" + " " * 10 + "[ticketmaster]")


def test_formatter_renders_body_kv_pairs_in_order():
    fmt = IngestionFormatter()
    rec = _make_record(
        logging.INFO, "fetch.done",
        {"adapter": "ticketmaster", "events": 612, "pages": 11, "elapsed_s": 33.4},
    )
    line = fmt.format(rec)
    # Adapter tag first, then key=val in insertion order, elapsed rendered as "33.4s".
    assert "[ticketmaster] events=612 pages=11 elapsed=33.4s" in line


def test_formatter_renders_dict_counter_as_brace_group():
    fmt = IngestionFormatter()
    rec = _make_record(
        logging.WARNING, "fetch.done",
        {"adapter": "ticketmaster", "events": 10, "warnings": {"wiki_fetch": 8, "detail_fetch": 2}},
    )
    line = fmt.format(rec)
    assert "warnings={wiki_fetch:8, detail_fetch:2}" in line


def test_formatter_quotes_strings_with_spaces():
    fmt = IngestionFormatter()
    rec = _make_record(
        logging.WARNING, "fetch.warn",
        {"adapter": "ticketmaster", "cat": "wiki_fetch", "first": "Bad Bunny"},
    )
    line = fmt.format(rec)
    assert 'first="Bad Bunny"' in line


def test_formatter_falls_back_for_legacy_records():
    fmt = IngestionFormatter()
    rec = logging.LogRecord(
        name="app.other", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello %s", args=("world",), exc_info=None,
    )
    line = fmt.format(rec)
    # Legacy path: still prints ts + level + msg. Event column is blank.
    assert "hello world" in line
    assert "INFO " in line


def test_configure_logging_installs_formatter_on_root():
    import io

    from app.ingestion.logging_util import configure_logging

    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        stream = io.StringIO()
        configure_logging(level=logging.INFO, stream=stream)
        logging.getLogger("app.ingestion.scheduler").info(
            "", extra={"event": "run.start", "body": {"run": "abcd", "sources": 2}},
        )
        output = stream.getvalue()
        assert "run.start" in output
        assert "run=abcd sources=2" in output
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)


def test_progress_reporter_throttles_to_interval(caplog):
    from app.ingestion.logging_util import ProgressReporter

    fake_now = [0.0]

    def clock():
        return fake_now[0]

    caplog.set_level(logging.INFO, logger="app.ingestion.progress")
    p = ProgressReporter("ticketmaster", interval_s=30.0, clock=clock)
    p.tick(page=1, events=60)              # first tick: no emission (start baseline)
    fake_now[0] = 10.0
    p.tick(page=2, events=120)             # under interval: silent
    fake_now[0] = 31.0
    p.tick(page=3, events=180)             # crossed interval: emit
    fake_now[0] = 45.0
    p.tick(page=4, events=240)             # under interval since last emit
    fake_now[0] = 62.0
    p.tick(page=5, events=300)             # crossed again: emit

    progress_records = [r for r in caplog.records if getattr(r, "event", None) == "fetch.progress"]
    assert len(progress_records) == 2
    assert progress_records[0].body == {
        "adapter": "ticketmaster", "page": 3, "events": 180, "elapsed_s": 31.0,
    }
    assert progress_records[1].body == {
        "adapter": "ticketmaster", "page": 5, "events": 300, "elapsed_s": 62.0,
    }


def test_progress_reporter_done_returns_final_state():
    from app.ingestion.logging_util import ProgressReporter

    fake_now = [0.0]
    p = ProgressReporter("ticketmaster", interval_s=30.0, clock=lambda: fake_now[0])
    p.tick(page=1, events=60)
    fake_now[0] = 33.4
    p.tick(page=11, events=612)
    result = p.done()
    assert result == {"page": 11, "events": 612, "elapsed_s": 33.4}


def test_warning_collector_first_per_cat_warn_rest_debug(caplog):
    from app.ingestion.logging_util import WarningCollector

    caplog.set_level(logging.DEBUG, logger="app.ingestion.warn")
    w = WarningCollector("ticketmaster")
    w.warn("wiki_fetch", "Bad Bunny")
    w.warn("wiki_fetch", "Beyoncé")
    w.warn("detail_fetch", "id-42")
    w.warn("wiki_fetch", "Coldplay")

    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(warns) == 2
    assert warns[0].body == {"adapter": "ticketmaster", "cat": "wiki_fetch", "first": "Bad Bunny"}
    assert warns[1].body == {"adapter": "ticketmaster", "cat": "detail_fetch", "first": "id-42"}
    assert len(debugs) == 2  # Beyoncé, Coldplay
    assert w.summary() == {"wiki_fetch": 3, "detail_fetch": 1}


def test_warning_collector_op_always_warn_not_counted(caplog):
    from app.ingestion.logging_util import WarningCollector

    caplog.set_level(logging.DEBUG, logger="app.ingestion.warn")
    w = WarningCollector("eventim")
    w.op("unexpected status", status=418, url="https://example.com")
    w.op("giving up on url", url="https://example.com", attempts=4)

    ops = [r for r in caplog.records if getattr(r, "event", None) == "fetch.op"]
    assert len(ops) == 2
    assert ops[0].levelno == logging.WARNING
    assert ops[0].body == {
        "adapter": "eventim", "msg": "unexpected status",
        "status": 418, "url": "https://example.com",
    }
    assert w.summary() == {}  # op() does not count


def test_warning_collector_warn_includes_exc_info(caplog):
    from app.ingestion.logging_util import WarningCollector

    caplog.set_level(logging.DEBUG, logger="app.ingestion.warn")
    w = WarningCollector("ohschonhell")
    try:
        raise ValueError("bad date")
    except ValueError as e:
        w.warn("bad_date", "https://example.com/x", exc=e)
        w.warn("bad_date", "https://example.com/y", exc=e)

    # Both records carry exc_info so tracebacks are preserved.
    assert all(r.exc_info is not None for r in caplog.records)
