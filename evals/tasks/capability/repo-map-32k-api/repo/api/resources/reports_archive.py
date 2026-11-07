"""The reports archive resource: a read-only list over a fixed sample."""

from api.paging import paginate

NAME = "reports_archive"
ROWS = [
    {"id": 1, "label": "reports_archive-bravo"},
    {"id": 2, "label": "reports_archive-cedar"},
    {"id": 3, "label": "reports_archive-delta"},
    {"id": 4, "label": "reports_archive-ember"},
    {"id": 5, "label": "reports_archive-fjord"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of reports archive, the first page being 1."""
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
