"""Turn a title into a URL slug."""

import re


def slugify(title: str) -> str:
    """Return the slug of *title*."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
