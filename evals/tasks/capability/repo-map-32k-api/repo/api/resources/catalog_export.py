"""The catalog export resource: a read-only list over a fixed sample."""

from api.paging import paginate

NAME = "catalog_export"
ROWS = [
    {"id": 1, "label": "catalog_export-fjord"},
    {"id": 2, "label": "catalog_export-grove"},
    {"id": 3, "label": "catalog_export-haze"},
    {"id": 4, "label": "catalog_export-alpha"},
    {"id": 5, "label": "catalog_export-bravo"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of catalog export, the first page being 1."""
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
