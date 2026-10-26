"""Bounded text with a visible cut.

Each cut leaves a marker, because a reader of a trace, a tool result or an audit line must be
able to tell that text is missing. The markers differ by where the text goes, and tests and
stored data match on them, so each has its own function instead of one shared option.
"""

from __future__ import annotations

from docket.kernel.errors import InvalidInput

MAX_COMMAND_CHARS = 1000


def one_line(text: str) -> str:
    """Collapse every run of whitespace, newlines included, to a single space."""
    return " ".join(text.split())


def ellipsize(text: str, limit: int, marker: str = "…") -> str:
    """*text* whole when it fits *limit*, else cut so that text plus *marker* is *limit* long."""
    if len(text) <= limit:
        return text
    return text[: max(limit - len(marker), 0)] + marker


def cut_chars(text: str, limit: int) -> str:
    """*text* cut to *limit* with ``…[truncated N chars]`` after it; a *limit* of 0 or less
    means unbounded. For values embedded in JSON attributes."""
    if limit <= 0 or len(text) <= limit:
        return text
    return f"{text[:limit]}…[truncated {len(text) - limit} chars]"


def cut_output(text: str, limit: int) -> str:
    """*text* cut to *limit* with a ``[truncated: N more characters]`` paragraph after it.
    For tool results a model reads."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n\n[truncated: {len(text) - limit} more characters]"


def check_command(value: object) -> str:
    """The command as one stripped line; raises ``InvalidInput`` for a NUL, a newline or too long."""
    text = str(value or "").strip()
    if "\x00" in text or "\n" in text or "\r" in text:
        raise InvalidInput("must be one line without a NUL byte")
    if len(text) > MAX_COMMAND_CHARS:
        raise InvalidInput(f"must be at most {MAX_COMMAND_CHARS} characters")
    return text
