import unittest

from sizes import human_size


class SizesTests(unittest.TestCase):
    def test_spec(self) -> None:
        self.assertEqual(human_size(1536), "1.5 KB")


if __name__ == "__main__":
    unittest.main()
