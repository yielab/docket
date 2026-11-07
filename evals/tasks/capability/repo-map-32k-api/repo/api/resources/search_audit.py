"""The search audit resource: a read-only list over a fixed sample."""

from api.paging import paginate

NAME = "search_audit"
ROWS = [
    {"id": 1, "label": "search_audit-fjord"},
    {"id": 2, "label": "search_audit-grove"},
    {"id": 3, "label": "search_audit-haze"},
    {"id": 4, "label": "search_audit-alpha"},
    {"id": 5, "label": "search_audit-bravo"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of search audit, the first page being 1."""
    return {
        "resource": NAME,
        "page": page,
        "size": size,
        "total": len(ROWS),
        "items": paginate(ROWS, page, size),
    }


def get(row_id: int) -> dict | None:
    """The row with *row_id*, or None."""
    for row in ROWS:
        if row["id"] == row_id:
            return row
    return None


def summary() -> str:
    """One line for the index page."""
    return f"{NAME}: {len(ROWS)} rows, first label {ROWS[0]['label']}"
