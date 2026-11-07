import checkout


def test_the_currency_argument_is_carried():
    meta = checkout.receipt_metadata("order-17", "EUR")
    assert meta["currency"] == "EUR"
    assert meta["tenant"] == "cobalt-7"
