# Earlier work in this session (state at the pause)

Decision: we will round half-even with decimal, not float, because bank totals must match.

I ran `pytest tests/test_invoice.py`; the last line was:
FAILED test_invoice.py::test_total - AssertionError: 10.01 != 10.00

Fix: edited src/billing/rounding.py: total now uses Decimal.quantize.

The test passes now. Still open: the monthly report in reports/monthly.py rounds the same way.

Operator: thanks, pause here. The files that follow are the tool output of the run.
