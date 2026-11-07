"""The reports import resource: a read-only list over a fixed sample."""

from api.paging import paginate

NAME = "reports_import"
ROWS = [
    {"id": 1, "label": "reports_import-grove"},
    {"id": 2, "label": "reports_import-haze"},
    {"id": 3, "label": "reports_import-alpha"},
    {"id": 4, "label": "reports_import-bravo"},
    {"id": 5, "label": "reports_import-cedar"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of reports import, the first page being 1."""
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
