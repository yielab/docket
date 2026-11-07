"""Checkout calculations and receipt metadata."""

TENANT = "cobalt-7"


def invoice_total(subtotal_cents: int, tax_basis_points: int) -> int:
    """Return the subtotal plus tax in cents."""
    tax_cents = round(subtotal_cents * tax_basis_points / 10_000)
    return subtotal_cents + tax_cents


def receipt_metadata(order_id: str) -> dict[str, str]:
    """Return stable metadata for a generated receipt."""
    return {"order_id": order_id, "tenant": TENANT}
