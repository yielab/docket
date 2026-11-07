"""The payments gateway resource: a read-only list over a fixed sample."""

from api.paging import paginate

NAME = "payments_gateway"
ROWS = [
    {"id": 1, "label": "payments_gateway-delta"},
    {"id": 2, "label": "payments_gateway-ember"},
    {"id": 3, "label": "payments_gateway-fjord"},
    {"id": 4, "label": "payments_gateway-grove"},
    {"id": 5, "label": "payments_gateway-haze"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of payments gateway, the first page being 1."""
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
