import checkout


def test_the_discount_rounds_half_up():
    assert checkout.apply_discount(1_005, 10) == 904
    assert checkout.apply_discount(15, 50) == 7
