import billing


def test_day_fourteen_is_still_inside_the_window():
    assert billing.refund_cents(900, 14, 300) == 900
    assert billing.refund_cents(900, 15, 300) == 300
