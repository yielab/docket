from decimal import Decimal

import money


def test_round_money_is_half_even():
    assert money.round_money(Decimal("2.345")) == Decimal("2.34")
    assert money.round_money(Decimal("2.355")) == Decimal("2.36")
