import unittest

from stats import median


class StatsTests(unittest.TestCase):
    def test_spec(self) -> None:
        self.assertEqual(median([3, 1, 2]), 2)


if __name__ == "__main__":
    unittest.main()
