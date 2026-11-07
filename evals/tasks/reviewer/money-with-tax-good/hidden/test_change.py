from decimal import Decimal

import money


def test_the_tax_rounds_half_to_even():
    assert money.with_tax(Decimal("10.50"), Decimal("0.01")) == Decimal("10.60")
    assert money.with_tax(Decimal("10.70"), Decimal("0.01")) == Decimal("10.81")
