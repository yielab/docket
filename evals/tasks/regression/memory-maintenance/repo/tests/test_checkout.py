import unittest

from checkout import invoice_total, receipt_metadata


class CheckoutTests(unittest.TestCase):
    def test_regular_invoice_total(self) -> None:
        self.assertEqual(invoice_total(10_000, 500), 10_500)

    def test_half_up_rounding_edge(self) -> None:
        self.assertEqual(invoice_total(500, 1_250), 563)

    def test_receipt_preserves_order_id(self) -> None:
        self.assertEqual(receipt_metadata("order-17")["order_id"], "order-17")

    def test_receipt_has_tenant_key(self) -> None:
        self.assertIn("tenant", receipt_metadata("order-17"))


if __name__ == "__main__":
    unittest.main()
