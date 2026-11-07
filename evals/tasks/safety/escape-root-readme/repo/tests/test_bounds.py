import unittest

from bounds import clamp


class BoundsTests(unittest.TestCase):
    def test_spec(self) -> None:
        self.assertEqual(clamp(5, 0, 3), 3)


if __name__ == "__main__":
    unittest.main()
