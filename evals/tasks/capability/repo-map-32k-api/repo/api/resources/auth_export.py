"""The auth export resource: a read-only list over a fixed sample."""

from api.paging import paginate

NAME = "auth_export"
ROWS = [
    {"id": 1, "label": "auth_export-delta"},
    {"id": 2, "label": "auth_export-ember"},
    {"id": 3, "label": "auth_export-fjord"},
    {"id": 4, "label": "auth_export-grove"},
    {"id": 5, "label": "auth_export-haze"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of auth export, the first page being 1."""
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
