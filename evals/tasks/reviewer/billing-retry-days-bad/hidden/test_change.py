import billing


def test_the_second_retry_is_seven_days_after_the_failure():
    assert billing.retry_days(10) == [13, 17]
