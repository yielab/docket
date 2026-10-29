"""What a built-in tool returns, shared by the tool set and the platform fetch adapter.

This is also the one place a tool result is cut. A result over ``DOCKET_TOOL_MAX_OUTPUT_CHARS``
is written whole, as plain text, to ``<pod cache>/artifacts/<sha256>.txt`` and the cut result
ends with a line naming that file, so lowering the cap loses nothing the model cannot read back.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from docket.kernel import text as _text
from docket.kernel.home import current_home

_ARTIFACT_LINE = re.compile(
    r"^\[full output: (.+) — read it with read\(path, offset, limit\)\]$", re.M
)
# The share of the cap a cut result keeps from its end, for output whose verdict is last.
VERDICT_TAIL = 0.6
_POD: ContextVar[str] = ContextVar("docket_tool_artifact_pod", default="")
# The turn's own output cap and read window, in characters; None keeps the home's values.
_OUTPUT_CHARS: ContextVar[int | None] = ContextVar("docket_tool_output_chars", default=None)
_READ_CHARS: ContextVar[int | None] = ContextVar("docket_tool_read_chars", default=None)


@dataclass
class ToolOutcome:
    """What happened when a tool ran. Not whether it was allowed to."""

    ok: bool
    content: str = ""
    error: str = ""
    refusal: str = ""


@contextmanager
def artifact_scope(
    pod: str, *, output_chars: int | None = None, read_chars: int | None = None
) -> Iterator[None]:
    """Store an over-cap result whole under *pod*'s cache while the block runs, and cut at the
    turn's *output_chars* and *read_chars* where given (``dispatch_tool`` opens it around every
    handler); outside it a cut result is only cut, at the home's cap."""
    tokens = (_POD.set(pod), _OUTPUT_CHARS.set(output_chars), _READ_CHARS.set(read_chars))
    try:
        yield
    finally:
        _READ_CHARS.reset(tokens[2])
        _OUTPUT_CHARS.reset(tokens[1])
        _POD.reset(tokens[0])


def _held_to_cap(chars: int | None, default: int) -> int:
    """*chars* when set, never above the home's tool-output cap, else *default*."""
    return default if chars is None else min(chars, current_home().tool_max_output_chars)


def read_window_chars(default: int) -> int:
    """The characters a ``read`` without a window returns: the turn's, else *default*."""
    return _held_to_cap(_READ_CHARS.get(), default)


def artifact_dir() -> Path | None:
    """The calling pod's artifacts directory, or ``None`` outside a scope or for an unknown pod."""
    pod = _POD.get()
    if not pod or Path(pod).name != pod or pod in (".", ".."):
        return None
    home = current_home()
    if not (home.pods_dir / pod).is_dir():
        return None
    return home.pod_cache_dir(pod) / "artifacts"


def artifact_path_in(text: str) -> str | None:
    """The artifact path a cut result names, or ``None`` when *text* carries no such line."""
    found = _ARTIFACT_LINE.findall(text)
    return found[-1] if found else None


def _store_artifact(text: str) -> Path | None:
    directory = artifact_dir()
    if directory is None:
        return None
    path = directory / f"{hashlib.sha256(text.encode('utf-8', 'replace')).hexdigest()}.txt"
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not path.exists():
            partial = path.with_suffix(".part")
            fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", errors="replace") as handle:
                handle.write(text)
            os.replace(partial, path)
    except OSError:
        return None
    return path


def bounded_text(text: str, tail: float = 0.0) -> str:
    """*text* whole when it fits the cap, else cut (keeping *tail* of the cap from the end) and,
    where the whole can be stored, ending with its artifact line, which counts against the cap."""
    limit = _held_to_cap(_OUTPUT_CHARS.get(), current_home().tool_max_output_chars)
    if len(text) <= limit:
        return text
    path = _store_artifact(text)
    if path is None:
        return _text.cut_output(text, limit, tail)
    line = f"[full output: {path} — read it with read(path, offset, limit)]"
    # The line counts against the cap, so a capped result stays about as long as it was.
    cut = _text.cut_output(text, max(limit - len(line), limit // 2), tail)
    return f"{cut}\n\n{line}"


def text_outcome(text: str, tail: float = 0.0) -> ToolOutcome:
    """A successful outcome carrying *text*, bounded like a ``read`` result."""
    return ToolOutcome(True, content=bounded_text(text, tail))
