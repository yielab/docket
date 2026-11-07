"""Money helpers. Totals use Decimal, never float (bank totals must match)."""

from decimal import ROUND_HALF_EVEN, Decimal

CENT = Decimal("0.01")


def round_money(amount: Decimal) -> Decimal:
    """Round to cents, half to even."""
    return amount.quantize(CENT, rounding=ROUND_HALF_EVEN)
