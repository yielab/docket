"""The shipping ledger resource: a read-only list over a fixed sample."""

from api.paging import paginate

NAME = "shipping_ledger"
ROWS = [
    {"id": 1, "label": "shipping_ledger-delta"},
    {"id": 2, "label": "shipping_ledger-ember"},
    {"id": 3, "label": "shipping_ledger-fjord"},
    {"id": 4, "label": "shipping_ledger-grove"},
    {"id": 5, "label": "shipping_ledger-haze"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of shipping ledger, the first page being 1."""
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
