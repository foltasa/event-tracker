"""Run the full ingestion pipeline once and exit.

Standalone trigger for the same `run_ingestion()` that the APScheduler cron
job and `POST /ingestion/run` use. No FastAPI app, no uvicorn — safe to call
from OS-cron / Windows Task Scheduler so the daily run does not depend on a
long-running backend process.

Usage from backend/: `python -m scripts.ingest`
"""
from __future__ import annotations

import sys

from app.ingestion.scheduler import run_ingestion


def main() -> int:
    try:
        report = run_ingestion()
    except Exception as exc:  # noqa: BLE001 — surface any failure to the caller
        print(f"ingestion failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"inserted={report.inserted} updated={report.updated} skipped={report.skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
