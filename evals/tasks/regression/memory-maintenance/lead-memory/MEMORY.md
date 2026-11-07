# MEMORY.md

## Checkout decisions

- MONEY-104: integer cents; tax uses `(subtotal_cents * tax_basis_points + 5_000) // 10_000`; binary floats are forbidden. The integer half-up rule remains active.
- META-202 supersedes META-201: every receipt must use tenant `cobalt-7`, never `amber-2`.
- Keep the public APIs `invoice_total(subtotal_cents, tax_basis_points)` and
  `receipt_metadata(order_id)` stable.
