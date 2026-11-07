import slug


def test_numbers_already_taken_are_skipped():
    assert slug.unique_slug("A b", {"a-b", "a-b-2"}) == "a-b-3"
    assert slug.unique_slug("A b", {"a-b", "a-b-2", "a-b-3"}) == "a-b-4"
