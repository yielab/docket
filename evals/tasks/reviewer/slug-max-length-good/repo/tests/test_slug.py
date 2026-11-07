import slug


def test_lowercases():
    assert slug.slugify("Hello World") == "hello-world"


def test_collapses_runs_of_separators():
    assert slug.slugify("a  --  b!!c") == "a-b-c"


def test_strips_the_ends():
    assert slug.slugify("  --Title?  ") == "title"
