"""Pure helpers for the agent-managed memory blobs (facts_md, taste_summary).

Single function `apply_edit` implements replace / append / remove with cap
enforcement. Tools in app.agent.tools wrap this with a DB session.
"""


class EditError(Exception):
    """Raised when an edit cannot be applied. Tools translate this to ToolError."""


def apply_edit(blob: str, old_string: str, new_string: str, *, cap: int, label: str) -> str:
    """Return the new blob after the edit. Never mutates input.

    Rules:
    - old="" and new!="" -> append new as a line at the end (one '\\n' separator
      if blob is non-empty and does not already end with '\\n').
    - old!="" and new!="" -> replace the unique occurrence of old with new.
    - old!="" and new=="" -> remove the unique occurrence of old.
    - old=="" and new=="" -> error (no-op).
    - If old!="" must appear exactly once (else error).
    - Resulting line count (via splitlines) must be <= cap.
    """
    if old_string == "" and new_string == "":
        raise EditError(f"{label}: no-op (both strings empty)")

    if old_string == "":
        # Append path
        if blob == "":
            candidate = new_string
        elif blob.endswith("\n"):
            candidate = blob + new_string
        else:
            candidate = blob + "\n" + new_string
    else:
        count = blob.count(old_string)
        if count == 0:
            raise EditError(f"{label}: old_string not found in current blob")
        if count > 1:
            raise EditError(f"{label}: old_string matches {count} locations; provide more context")
        candidate = blob.replace(old_string, new_string, 1)

    lines = len(candidate.splitlines())
    if lines > cap:
        raise EditError(f"{label} would exceed cap: {lines} lines vs. limit {cap}; compress first")

    return candidate
