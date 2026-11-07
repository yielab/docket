import unittest

from temps import c_to_f


class TempsTests(unittest.TestCase):
    def test_spec(self) -> None:
        self.assertEqual(c_to_f(100), 212.0)


if __name__ == "__main__":
    unittest.main()
