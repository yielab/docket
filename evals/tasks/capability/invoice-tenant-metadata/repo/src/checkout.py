"""Checkout calculations and receipt metadata."""

from tenancy import current_tenant

TENANT = current_tenant()


def invoice_total(subtotal_cents: int, tax_basis_points: int) -> int:
    """Return the subtotal plus tax in cents; a half cent of tax rounds up."""
    tax_cents = (subtotal_cents * tax_basis_points + 5_000) // 10_000
    return subtotal_cents + tax_cents


def receipt_metadata(order_id: str) -> dict[str, str]:
    """Return stable metadata for a generated receipt."""
    return {"order_id": order_id, "tenant": TENANT}
