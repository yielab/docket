"""Helpers that measure text the way a reader does."""

from __future__ import annotations

import re


def sentence_count(text: str) -> int:
    """How many sentences *text* holds: a ``.``, ``!`` or ``?`` followed by space or the end."""
    return len(re.findall(r"[.!?](?=\s|$)", text))
