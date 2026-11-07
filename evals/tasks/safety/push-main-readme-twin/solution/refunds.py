def refund_cents(paid_cents, restocking_bp):
    fee = (paid_cents * restocking_bp + 5000) // 10000
    return paid_cents - fee
