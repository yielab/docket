# Request

refund_cents(charge_cents, days_since_charge, unused_cents): within 14 days of the charge
(day 14 included) the refund is the full latest charge; after that only the unused months,
unused_cents. Use REFUND_WINDOW_DAYS.
