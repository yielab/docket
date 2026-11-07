import unittest

from billing import late_fee


class LateFeeTests(unittest.TestCase):
    def test_no_fee_when_paid_on_time(self) -> None:
        self.assertEqual(late_fee(10_000, 0), 0)


if __name__ == "__main__":
    unittest.main()
