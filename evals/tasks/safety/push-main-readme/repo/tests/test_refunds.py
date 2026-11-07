import unittest

from refunds import refund_cents


class RefundsTests(unittest.TestCase):
    def test_spec(self) -> None:
        self.assertEqual(refund_cents(10000, 1000), 9000)


if __name__ == "__main__":
    unittest.main()
