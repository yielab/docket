import regions


def test_the_last_window_counts():
    assert regions.window_sums([1, 2, 3, 4], 2) == [3, 5, 7]
    assert regions.window_sums([5, 5], 2) == [10]
