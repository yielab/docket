"""Billing rules."""

GRACE_BALANCE_CENTS = 500


def late_fee(balance_cents: int, days_late: int) -> int:
    """The fee, in cents, for a balance paid ``days_late`` days after its due date."""
    if balance_cents < GRACE_BALANCE_CENTS:
        return 0
    weeks = max(days_late, 0) // 7
    return min(balance_cents * 2 * weeks, balance_cents * 10) // 100
