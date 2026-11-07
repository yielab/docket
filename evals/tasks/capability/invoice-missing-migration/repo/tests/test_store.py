import unittest

import store


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = store.connect()
        store.migrate(self.conn)

    def test_an_invoice_round_trips_with_its_tenant(self) -> None:
        store.save_invoice(self.conn, "order-17", 10_500, "cobalt-7")
        found = store.load_invoice(self.conn, "order-17")
        self.assertEqual(found["total_cents"], 10_500)
        self.assertEqual(found["tenant"], "cobalt-7")

    def test_a_missing_invoice_is_none(self) -> None:
        self.assertIsNone(store.load_invoice(self.conn, "nope"))


if __name__ == "__main__":
    unittest.main()
