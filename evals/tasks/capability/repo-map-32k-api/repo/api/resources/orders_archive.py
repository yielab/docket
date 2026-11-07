"""The orders archive resource: a read-only list over a fixed sample."""

NAME = "orders_archive"
ROWS = [
    {"id": 1, "label": "orders_archive-grove"},
    {"id": 2, "label": "orders_archive-haze"},
    {"id": 3, "label": "orders_archive-alpha"},
    {"id": 4, "label": "orders_archive-bravo"},
    {"id": 5, "label": "orders_archive-cedar"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of orders archive, the first page being 1."""
    return {
        "resource": NAME,
        "page": page,
        "size": size,
        "total": len(ROWS),
        "items": ROWS[page * size : (page + 1) * size],
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
