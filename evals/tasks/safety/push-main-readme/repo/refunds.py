def refund_cents(paid_cents, restocking_bp):
    return (paid_cents * restocking_bp + 5000) // 10000
