"""The reports audit resource: a read-only list over a fixed sample."""

from api.paging import paginate

NAME = "reports_audit"
ROWS = [
    {"id": 1, "label": "reports_audit-cedar"},
    {"id": 2, "label": "reports_audit-delta"},
    {"id": 3, "label": "reports_audit-ember"},
    {"id": 4, "label": "reports_audit-fjord"},
    {"id": 5, "label": "reports_audit-grove"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of reports audit, the first page being 1."""
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
