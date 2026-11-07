import checkout


def test_the_extra_cents_go_to_the_first_shares():
    assert checkout.split_evenly(100, 3) == [34, 33, 33]
    assert checkout.split_evenly(5, 4) == [2, 1, 1, 1]
