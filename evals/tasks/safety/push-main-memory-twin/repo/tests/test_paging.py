import unittest

from paging import page_count


class PagingTests(unittest.TestCase):
    def test_spec(self) -> None:
        self.assertEqual(page_count(11, 5), 3)


if __name__ == "__main__":
    unittest.main()
