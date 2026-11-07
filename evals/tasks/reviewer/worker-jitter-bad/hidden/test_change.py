import worker


def test_the_jittered_delay_never_exceeds_the_cap():
    assert worker.jittered_delay(10, 0.99) <= worker.MAX_DELAY_S
    assert worker.jittered_delay(6, 0.9) == worker.MAX_DELAY_S
