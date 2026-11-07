"""The catalog gateway resource: a read-only list over a fixed sample."""

from api.paging import paginate

NAME = "catalog_gateway"
ROWS = [
    {"id": 1, "label": "catalog_gateway-grove"},
    {"id": 2, "label": "catalog_gateway-haze"},
    {"id": 3, "label": "catalog_gateway-alpha"},
    {"id": 4, "label": "catalog_gateway-bravo"},
    {"id": 5, "label": "catalog_gateway-cedar"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of catalog gateway, the first page being 1."""
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
