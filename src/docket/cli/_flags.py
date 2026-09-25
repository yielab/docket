"""Shared unknown-flag detection for hand-dispatched CLI commands.

`roles`, `gates`, `keys`, `policies`, and `maintain` declare
`context_settings={"allow_extra_args": True, "ignore_unknown_options": True}` and parse their own
trailing `ctx.args` instead of Click's option parser, so an undocumented `--flag` would otherwise
land silently in a positional slot rather than raising a usage error. `find_unknown_flag` restores
that check for the flag spellings each command actually documents.
"""

from __future__ import annotations


def find_unknown_flag(args: list[str], documented: frozenset[str]) -> str | None:
    """Return the first `-`-led token in `args` that is not in `documented`, else `None`."""
    for tok in args:
        if tok.startswith("-") and tok not in documented:
            return tok
    return None
