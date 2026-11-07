"""The auth audit resource: a read-only list over a fixed sample."""

from api.paging import paginate

NAME = "auth_audit"
ROWS = [
    {"id": 1, "label": "auth_audit-bravo"},
    {"id": 2, "label": "auth_audit-cedar"},
    {"id": 3, "label": "auth_audit-delta"},
    {"id": 4, "label": "auth_audit-ember"},
    {"id": 5, "label": "auth_audit-fjord"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of auth audit, the first page being 1."""
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
