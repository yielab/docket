import unittest

from csvline import split_fields


class CsvlineTests(unittest.TestCase):
    def test_spec(self) -> None:
        self.assertEqual(split_fields("a, b ,c"), ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
