"""The root of every failure docket raises on purpose, and the kinds a boundary reacts to.

Application and adapter code raise; ``interfaces/cli`` and ``interfaces/http`` catch ``DocketError`` once at the edge
and turn ``message`` and ``hint`` into output or a status. A new class goes under the kind whose
reaction it shares; a new kind needs a reaction no existing one has. A signal that is part of
normal operation (a task parked, an approval already decided the same way) is not a failure and
does not derive from ``DocketError``. ``InvalidInput`` and ``NotFound`` also derive from
``ValueError`` and ``LookupError`` so code catching the builtins keeps working.
"""

from __future__ import annotations

from pathlib import Path


class DocketError(Exception):
    """A failure with something to tell the operator: what went wrong, and optionally what to do."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class InvalidInput(DocketError, ValueError):
    """The caller supplied something that cannot be accepted; fixing the input fixes it."""


class CanonicalFormRefused(InvalidInput):
    """An authored document is written in the canonical shape instead of its one short form; the
    message names the short-form key to write, and a command exits 2 (refused as written)."""


class NotFound(DocketError, LookupError):
    """The thing asked about does not exist."""


class DispatchError(InvalidInput):
    """A pod cannot be dispatched (no pod, no lead, ...)."""


class Conflict(DocketError):
    """The request is well formed but contradicts the current state, which has already moved."""


class Refused(DocketError):
    """A rule or a limit forbids this request, however it is phrased."""


class Unavailable(DocketError):
    """Something docket depends on failed; the same request may succeed later."""


class DocumentError(InvalidInput):
    """``file: field: message (valid: a, b)``; ``valid`` is set only for a closed vocabulary."""

    def __init__(
        self, file: Path | str, field: str, message: str, valid: tuple[str, ...] = ()
    ) -> None:
        self.file = Path(file)
        self.field = field
        self.valid = tuple(valid)
        super().__init__(message)
        Exception.__init__(self, str(self))

    def __str__(self) -> str:
        rendered = f"{self.file}: {self.field}: {self.message}"
        if self.valid:
            rendered = f"{rendered} (valid: {', '.join(self.valid)})"
        return rendered
