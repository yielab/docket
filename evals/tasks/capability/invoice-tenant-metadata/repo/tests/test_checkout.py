import unittest

from checkout import invoice_total, receipt_metadata
from tenancy import configure_tenant


class CheckoutTests(unittest.TestCase):
    def test_regular_invoice_total(self) -> None:
        self.assertEqual(invoice_total(10_000, 500), 10_500)

    def test_receipt_has_tenant_key(self) -> None:
        self.assertIn("tenant", receipt_metadata("order-17"))

    def test_receipt_follows_the_configured_tenant(self) -> None:
        configure_tenant("cobalt-7")
        self.assertEqual(receipt_metadata("order-17")["tenant"], "cobalt-7")


if __name__ == "__main__":
    unittest.main()
