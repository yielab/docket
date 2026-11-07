import unittest

from ranges import overlaps


class RangesTests(unittest.TestCase):
    def test_spec(self) -> None:
        self.assertTrue(overlaps((1, 3), (3, 5)))


if __name__ == "__main__":
    unittest.main()
