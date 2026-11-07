"""The tenant receipts are issued for."""

_current = "amber-2"


def configure_tenant(name: str) -> None:
    """Make *name* the tenant of every receipt issued from now on."""
    global _current
    _current = name


def current_tenant() -> str:
    """The tenant most recently configured."""
    return _current
