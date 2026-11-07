"""Turn a title into a URL slug."""


def slugify(title: str) -> str:
    """Return the slug of *title*."""
    return title.replace(" ", "-")
