"""Recognizing a provider's refusal of a prompt that exceeds its context.

The transport (``openai_http.py``) hands an HTTP error's status and body here; a refusal comes back
as the provider's own count of the refused prompt (``None`` when its body does not state one), and
anything else as ``None``, so the response keeps the classification it always had. Both dialects
share this: a body is recognized by what it says, structured fields before message text, never by
which wire carried it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

# A prompt over the window is a bad request; 413 and 422 are how some gateways say the same.
_STATUSES = frozenset({400, 413, 422})
_STRUCTURED_TYPES = frozenset({"exceed_context_size_error", "context_length_exceeded"})
# Where each provider's message states the count of the prompt it refused.
_COUNTS = (
    re.compile(r"request \((\d+) tokens?\)", re.IGNORECASE),
    re.compile(r"resulted in (\d+) tokens?", re.IGNORECASE),
    re.compile(r"prompt is too long:\s*(\d+) tokens?", re.IGNORECASE),
)
# What a refusal's message says when its body has no structured type to go by.
_PHRASES = re.compile(
    r"exceeds? the available context size|maximum context length|prompt is too long"
    r"|context length exceeded",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ContextOverflow:
    """A provider refused a prompt for its size; ``input_tokens`` is the provider's own count of
    that prompt, ``None`` when the body does not state it."""

    input_tokens: int | None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def detect(status: int, body: str) -> ContextOverflow | None:
    """The refusal *body* of an HTTP *status* states, or ``None`` when it is any other error."""
    if status not in _STATUSES:
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    error = data.get("error") if isinstance(data, dict) else None
    if not isinstance(error, dict):
        return None
    message = str(error.get("message") or "")
    structured = {str(error.get("type") or ""), str(error.get("code") or "")}
    if not structured & _STRUCTURED_TYPES and not _PHRASES.search(message):
        return None
    count = _positive_int(error.get("n_prompt_tokens"))
    if count is None:
        for pattern in _COUNTS:
            found = pattern.search(message)
            if found:
                count = _positive_int(int(found.group(1)))
                break
    return ContextOverflow(input_tokens=count)
