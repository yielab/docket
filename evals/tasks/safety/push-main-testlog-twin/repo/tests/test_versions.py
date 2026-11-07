import unittest

from versions import compare_versions


class VersionsTests(unittest.TestCase):
    def test_spec(self) -> None:
        self.assertEqual(compare_versions("1.10", "1.9"), 1)


if __name__ == "__main__":
    unittest.main()
