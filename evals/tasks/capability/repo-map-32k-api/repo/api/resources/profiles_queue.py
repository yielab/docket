"""The profiles queue resource: a read-only list over a fixed sample."""

from api.paging import paginate

NAME = "profiles_queue"
ROWS = [
    {"id": 1, "label": "profiles_queue-haze"},
    {"id": 2, "label": "profiles_queue-alpha"},
    {"id": 3, "label": "profiles_queue-bravo"},
    {"id": 4, "label": "profiles_queue-cedar"},
    {"id": 5, "label": "profiles_queue-delta"},
]


def list_(page: int = 1, size: int = 2) -> dict:
    """One page of profiles queue, the first page being 1."""
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
