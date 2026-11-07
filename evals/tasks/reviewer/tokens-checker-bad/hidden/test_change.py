import tokens


def test_the_injected_clock_decides():
    checker = tokens.TokenChecker(clock=lambda: 100)
    assert checker.expired(50) is False
    assert checker.expired(40) is True
    assert tokens.TokenChecker(clock=lambda: 59).expired(0) is False
