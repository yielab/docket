import billing


def test_december_rolls_into_january_of_the_next_year():
    assert billing.payout_date(2026, 12) == (2027, 1, 15)
