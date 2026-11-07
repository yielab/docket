"""The billing cache resource: a read-only list over a fixed sample."""

from api.paging import paginate

NAME = "billing_cache"
ROWS = [
    {"id": 1, "label": "billing_cache-delta"},
    {"id": 2, "label": "billing_cache-ember"},
    {"id": 3, "label": "billing_cache-fjord"},
    {"id": 4, "label": "billing_cache-grove"},
    {"id": 5, "label": "billing_cache-haze"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of billing cache, the first page being 1."""
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
