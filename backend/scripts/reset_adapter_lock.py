"""Clear a source adapter's circuit-breaker state.

Usage:
    python -m scripts.reset_adapter_lock <source> [--yes]

Prints the current trip state (timestamp, reason, runs_while_disabled) and
asks for confirmation before clearing. Use --yes to skip the prompt.

Reminder: if the trip reason was persistent (e.g. Akamai fingerprint drift),
resetting alone will re-trip on the next run. Verify HTTP headers / adapter
config before running this."""
from __future__ import annotations

import argparse
import sys

from app.db.models.ingestion_state import IngestionState
from app.db.session import SessionLocal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clear a source adapter's circuit-breaker state.")
    parser.add_argument("source", help="Adapter source name (e.g. 'eventim')")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args(argv)

    session = SessionLocal()
    try:
        row = session.get(IngestionState, args.source)
        if row is None:
            print(f"error: source '{args.source}' not found in ingestion_state", file=sys.stderr)
            return 1
        if row.disabled_at is None:
            print(f"'{args.source}' is not tripped - no trip state to clear.")
            return 0

        print(f"Current trip state for '{args.source}':")
        print(f"  disabled_at:         {row.disabled_at.isoformat()}")
        print(f"  disabled_reason:     {row.disabled_reason}")
        print(f"  runs_while_disabled: {row.runs_while_disabled}")
        print()
        print("Reminder: verify HTTP headers / adapter config before resetting,")
        print("otherwise the breaker will re-trip on the next run.")
        print()

        if not args.yes:
            resp = input(f"Reset '{args.source}' circuit breaker? [y/N]: ").strip().lower()
            if resp not in ("y", "yes"):
                print("aborted.")
                return 0

        row.disabled_at = None
        row.disabled_reason = None
        row.runs_while_disabled = 0
        session.commit()
        print(f"'{args.source}' circuit breaker reset.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
