"""The reports sync resource: a read-only list over a fixed sample."""

from api.paging import paginate

NAME = "reports_sync"
ROWS = [
    {"id": 1, "label": "reports_sync-bravo"},
    {"id": 2, "label": "reports_sync-cedar"},
    {"id": 3, "label": "reports_sync-delta"},
    {"id": 4, "label": "reports_sync-ember"},
    {"id": 5, "label": "reports_sync-fjord"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of reports sync, the first page being 1."""
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
