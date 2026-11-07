import worker


def test_every_retry_is_counted():
    assert worker.total_wait(1) == 1
    assert worker.total_wait(4) == 15
    assert worker.total_wait(8) == 1 + 2 + 4 + 8 + 16 + 30 + 30 + 30
