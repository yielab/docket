import regions


def test_the_share_rounds_half_up():
    assert regions.share_bp(2, 3) == 6_667
    assert regions.share_bp(1, 16_001) == 1
