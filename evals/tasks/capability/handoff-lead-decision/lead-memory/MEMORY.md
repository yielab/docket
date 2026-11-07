# MEMORY.md

## Billing decisions

- LATE-FEE-31 (current; it supersedes LATE-FEE-12's flat 5 dollars): the late fee is 2 percent
  of the balance for every full 7 days late (days_late // 7 weeks), simple and not compounding,
  capped at 10 percent of the balance. Whole cents, rounded down once, after the cap. A balance
  under 500 cents never pays a fee.
- Keep the public signature `late_fee(balance_cents, days_late)` stable.
