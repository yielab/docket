import tokens


def test_the_boundary_second_is_expired():
    assert tokens.is_expired(0, 60) is True
    assert tokens.is_expired(0, 59) is False
