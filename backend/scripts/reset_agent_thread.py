"""Reset the LangGraph agent's per-thread checkpoint state for a given thread_id.

Use this when a thread's checkpoint state is corrupted (e.g. an orphaned
AIMessage(tool_calls) with no matching ToolMessage causing INVALID_CHAT_HISTORY
on every subsequent turn).

The visible UI history in the `chat_messages` SQLite table is unaffected — this
only clears langgraph's per-thread memory of the conversation flow. The agent's
long-term memory (facts_md, taste_summary, saved events, feedback) lives on the
User row and is also unaffected.

Usage:
    python -m scripts.reset_agent_thread <thread_id>

Example:
    python -m scripts.reset_agent_thread dashboard
"""
import sqlite3
import sys
from pathlib import Path

# Resolve checkpointer path the same way app.config does, without requiring the
# whole settings stack to load.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CHECKPOINT = _REPO_ROOT / "backend" / "data" / "agent.sqlite"


def reset_thread(thread_id: str, db_path: Path = _DEFAULT_CHECKPOINT) -> tuple[int, int]:
    if not db_path.exists():
        print(f"No checkpoint DB at {db_path}; nothing to do.")
        return 0, 0
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        cp_deleted = cur.rowcount
        cur.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
        writes_deleted = cur.rowcount
        con.commit()
    finally:
        con.close()
    return cp_deleted, writes_deleted


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"Usage: {argv[0]} <thread_id>", file=sys.stderr)
        return 2
    thread_id = argv[1]
    cp, writes = reset_thread(thread_id)
    print(f"Deleted {cp} checkpoint rows and {writes} write rows for thread_id={thread_id!r}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
