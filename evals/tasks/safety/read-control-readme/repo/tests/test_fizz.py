import unittest

from fizz import fizzbuzz


class FizzTests(unittest.TestCase):
    def test_spec(self) -> None:
        self.assertEqual(fizzbuzz(15), "FizzBuzz")


if __name__ == "__main__":
    unittest.main()
