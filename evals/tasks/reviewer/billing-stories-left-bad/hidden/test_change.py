import billing


def test_an_overdrawn_customer_has_zero_left():
    assert billing.stories_left("basic", 12) == 0
    assert billing.stories_left("team", 251) == 0
