import billing


def test_a_quota_covers_exactly_its_size():
    assert billing.cheapest_plan(10) == "basic"
    assert billing.cheapest_plan(60) == "pro"
    assert billing.cheapest_plan(250) == "team"
