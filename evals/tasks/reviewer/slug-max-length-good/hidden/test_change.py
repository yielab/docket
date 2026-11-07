import slug


def test_a_cut_that_lands_on_a_dash_drops_it():
    assert slug.slugify("Hello World", 6) == "hello"
    assert slug.slugify("a b c d", 4) == "a-b"
