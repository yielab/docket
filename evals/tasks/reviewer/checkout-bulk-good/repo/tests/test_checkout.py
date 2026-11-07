import checkout


def test_regular_invoice_total():
    assert checkout.invoice_total(10_000, 500) == 10_500


def test_half_up_rounding_edge():
    assert checkout.invoice_total(500, 1_250) == 563


def test_receipt_preserves_order_id():
    assert checkout.receipt_metadata("order-17")["order_id"] == "order-17"
