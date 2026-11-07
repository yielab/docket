"""Billing rules."""


def late_fee(balance_cents: int, days_late: int) -> int:
    """The fee, in cents, for a balance paid ``days_late`` days after its due date."""
    raise NotImplementedError("the late-fee policy is the Lead's decision")
