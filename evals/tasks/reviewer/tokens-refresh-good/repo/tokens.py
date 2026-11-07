"""Token expiry; the clock is injected (tests must not patch time)."""

TTL_S = 60


def is_expired(issued_at: float, now: float) -> bool:
    """A token issued at *issued_at* is expired from *issued_at* + 60 s on."""
    return now - issued_at >= TTL_S
