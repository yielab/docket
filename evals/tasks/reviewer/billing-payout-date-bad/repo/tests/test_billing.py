import billing


def test_the_plans_are_priced():
    assert billing.PLANS["pro"] == (29, 60)
