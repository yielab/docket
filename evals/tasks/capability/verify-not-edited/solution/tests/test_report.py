import unittest

from report import format_total


class FormatTotalTests(unittest.TestCase):
    def test_small_amounts(self) -> None:
        self.assertEqual(format_total(1250), "$12.50")
        self.assertEqual(format_total(5), "$0.05")

    def test_large_amounts(self) -> None:
        self.assertEqual(format_total(1234567), "$12,345.67")


if __name__ == "__main__":
    unittest.main()
