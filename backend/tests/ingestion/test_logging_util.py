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
