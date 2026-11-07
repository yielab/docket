import unittest

from slug import slugify


class SlugTests(unittest.TestCase):
    def test_lowercases(self) -> None:
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_collapses_runs_of_separators(self) -> None:
        self.assertEqual(slugify("a  --  b!!c"), "a-b-c")

    def test_strips_the_ends(self) -> None:
        self.assertEqual(slugify("  --Title?  "), "title")


if __name__ == "__main__":
    unittest.main()
