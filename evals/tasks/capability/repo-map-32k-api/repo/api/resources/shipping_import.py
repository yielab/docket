"""The shipping import resource: a read-only list over a fixed sample."""

from api.paging import paginate

NAME = "shipping_import"
ROWS = [
    {"id": 1, "label": "shipping_import-cedar"},
    {"id": 2, "label": "shipping_import-delta"},
    {"id": 3, "label": "shipping_import-ember"},
    {"id": 4, "label": "shipping_import-fjord"},
    {"id": 5, "label": "shipping_import-grove"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of shipping import, the first page being 1."""
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
