"""The message a step receives when it runs again over rounds its last turn already made.

Pure text: the shell in ``hops/application/runner.py`` gathers the facts (the error, the hop's
summary, the changed paths) and calls ``continuation_message``. See pod-dispatch.spec.md
("Retries and the failure-kind taxonomy" requirement 6).
"""

from __future__ import annotations

from collections.abc import Sequence

MAX_CHANGED_PATHS = 20


def continuation_message(error: str, summary: str, changed: Sequence[str]) -> str:
    """One fixed paragraph: the previous turn on this step stopped before it finished (and why),
    what the hop reported, up to ``MAX_CHANGED_PATHS`` changed paths, and the instruction to
    continue rather than start over. Empty *summary* and *changed* leave their sentence out."""
    parts = [
        "The previous turn on this step stopped before it finished"
        + (f": {error.strip()}." if error.strip() else ".")
    ]
    if summary.strip():
        parts.append(f"What it reported: {summary.strip()}")
    if changed:
        shown = ", ".join(changed[:MAX_CHANGED_PATHS])
        more = len(changed) - MAX_CHANGED_PATHS
        parts.append(
            f"Paths changed in the working tree so far: {shown}"
            + (f" (+{more} more)." if more > 0 else ".")
        )
    parts.append("Continue from where you stopped; do not start over; finish as the step asks.")
    return " ".join(parts)
