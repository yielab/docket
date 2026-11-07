"""The search gateway resource: a read-only list over a fixed sample."""

from api.paging import paginate

NAME = "search_gateway"
ROWS = [
    {"id": 1, "label": "search_gateway-alpha"},
    {"id": 2, "label": "search_gateway-bravo"},
    {"id": 3, "label": "search_gateway-cedar"},
    {"id": 4, "label": "search_gateway-delta"},
    {"id": 5, "label": "search_gateway-ember"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of search gateway, the first page being 1."""
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
