"""Money formatting for reports."""


def format_total(cents: int) -> str:
    """Format an amount in cents as dollars with thousands grouped, for example 1250 -> '$12.50'."""
    return f"${cents // 100:,}.{cents % 100:02d}"
