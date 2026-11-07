"""Pagination shared by every resource."""

from collections.abc import Sequence
from typing import Any


def paginate(rows: Sequence[Any], page: int, size: int) -> list[Any]:
    """Rows *size* at a time; the first page is 1."""
    start = (page - 1) * size
    return list(rows[start : start + size])
