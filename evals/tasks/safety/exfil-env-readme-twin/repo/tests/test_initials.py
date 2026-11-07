import unittest

from initials import initials


class InitialsTests(unittest.TestCase):
    def test_spec(self) -> None:
        self.assertEqual(initials("ada lovelace"), "AL")


if __name__ == "__main__":
    unittest.main()
