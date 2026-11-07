"""Retry policy of the queue worker: exponential backoff, capped (the broker sheds load on bursts)."""

MAX_DELAY_S = 30


def backoff_delay(attempt: int) -> int:
    """Seconds to wait before retry number *attempt* (1 is the first): 1, 2, 4, ... capped."""
    return min(MAX_DELAY_S, 2 ** (attempt - 1))
