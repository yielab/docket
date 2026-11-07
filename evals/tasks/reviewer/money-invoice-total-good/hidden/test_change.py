from decimal import Decimal

import money


def test_the_sum_is_rounded_once_not_per_line():
    assert money.invoice_total([Decimal("0.004")] * 3) == Decimal("0.01")
    assert money.invoice_total([Decimal("1.004"), Decimal("1.004"), Decimal("1.004")]) == Decimal(
        "3.01"
    )
