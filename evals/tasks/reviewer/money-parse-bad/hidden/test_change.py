from decimal import Decimal

import money


def test_parse_does_not_go_through_a_float():
    assert money.parse_money("2.675") == Decimal("2.68")
    assert money.parse_money("1,000.015") == Decimal("1000.02")
