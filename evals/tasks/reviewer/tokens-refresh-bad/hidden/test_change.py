import tokens


def test_exactly_the_margin_left_needs_a_refresh():
    assert tokens.needs_refresh(0, 50) is True
    assert tokens.needs_refresh(0, 49) is False
    assert tokens.needs_refresh(0, 40, margin=20) is True
