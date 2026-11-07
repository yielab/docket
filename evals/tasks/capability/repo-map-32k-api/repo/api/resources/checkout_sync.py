"""The checkout sync resource: a read-only list over a fixed sample."""

from api.paging import paginate

NAME = "checkout_sync"
ROWS = [
    {"id": 1, "label": "checkout_sync-delta"},
    {"id": 2, "label": "checkout_sync-ember"},
    {"id": 3, "label": "checkout_sync-fjord"},
    {"id": 4, "label": "checkout_sync-grove"},
    {"id": 5, "label": "checkout_sync-haze"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of checkout sync, the first page being 1."""
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
