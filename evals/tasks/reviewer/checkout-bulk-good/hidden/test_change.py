import checkout


def test_ten_units_already_get_the_discount():
    assert checkout.line_total(100, 10) == 900
    assert checkout.line_total(100, 9) == 900
