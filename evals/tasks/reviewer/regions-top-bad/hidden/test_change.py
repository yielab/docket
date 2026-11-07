import regions


def test_ties_are_in_name_order_whatever_the_input_order():
    assert regions.top_regions({"b": 5, "a": 5, "c": 1}, 2) == ["a", "b"]
    assert regions.top_regions({"z": 2, "y": 2}, 2) == ["y", "z"]
