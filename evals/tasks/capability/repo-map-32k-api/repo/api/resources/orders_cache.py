"""The orders cache resource: a read-only list over a fixed sample."""

from api.paging import paginate

NAME = "orders_cache"
ROWS = [
    {"id": 1, "label": "orders_cache-alpha"},
    {"id": 2, "label": "orders_cache-bravo"},
    {"id": 3, "label": "orders_cache-cedar"},
    {"id": 4, "label": "orders_cache-delta"},
    {"id": 5, "label": "orders_cache-ember"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of orders cache, the first page being 1."""
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
