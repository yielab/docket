import worker


def test_the_delay_doubles():
    assert [worker.backoff_delay(n) for n in (1, 2, 3, 4)] == [1, 2, 4, 8]


def test_the_delay_is_capped():
    assert worker.backoff_delay(10) == 30
