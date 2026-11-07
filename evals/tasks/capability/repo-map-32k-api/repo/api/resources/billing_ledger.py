"""The billing ledger resource: a read-only list over a fixed sample."""

from api.paging import paginate

NAME = "billing_ledger"
ROWS = [
    {"id": 1, "label": "billing_ledger-haze"},
    {"id": 2, "label": "billing_ledger-alpha"},
    {"id": 3, "label": "billing_ledger-bravo"},
    {"id": 4, "label": "billing_ledger-cedar"},
    {"id": 5, "label": "billing_ledger-delta"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of billing ledger, the first page being 1."""
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
