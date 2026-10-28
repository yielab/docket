"""Bounded text with a visible cut.

Each cut leaves a marker, because a reader of a trace, a tool result or an audit line must be
able to tell that text is missing. The markers differ by where the text goes, and tests and
stored data match on them, so each has its own function instead of one shared option.
"""

from __future__ import annotations

import re

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


def cut_output(text: str, limit: int, tail: float = 0.0) -> str:
    """*text* cut to *limit* with a ``[truncated: N more characters]`` paragraph, for tool results.
    The head is kept; a *tail* share (0.6) of *limit* is instead the end of *text*, after the
    paragraph, for output whose verdict is last."""
    if len(text) <= limit:
        return text
    marker = f"[truncated: {len(text) - limit} more characters]"
    tail_chars = int(limit * tail) if tail > 0 else 0
    if not tail_chars:
        return f"{text[:limit]}\n\n{marker}"
    return f"{text[: limit - tail_chars]}\n\n{marker}\n\n{text[len(text) - tail_chars :]}"


_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")


def normalize_output(text: str) -> str:
    """*text* without what costs context and says nothing: ANSI escape sequences are removed, a
    line rewritten with ``\\r`` keeps its last state (``\\r\\n`` is an ordinary newline), and a run of
    identical non-blank lines becomes ``line  [x N]``. Nothing else changes."""
    out: list[str] = []
    run = 0
    previous: str | None = None
    for raw in text.split("\n"):
        line = _ANSI.sub("", raw.removesuffix("\r").rsplit("\r", 1)[-1])
        if line and line == previous:
            run += 1
            continue
        if run:
            out[-1] = f"{previous}  [x {run + 1}]"
        out.append(line)
        previous, run = line, 0
    if run:
        out[-1] = f"{previous}  [x {run + 1}]"
    return "\n".join(out)


def check_command(value: object) -> str:
    """The command as one stripped line; raises ``InvalidInput`` for a NUL, a newline or too long."""
    text = str(value or "").strip()
    if "\x00" in text or "\n" in text or "\r" in text:
        raise InvalidInput("must be one line without a NUL byte")
    if len(text) > MAX_COMMAND_CHARS:
        raise InvalidInput(f"must be at most {MAX_COMMAND_CHARS} characters")
    return text
