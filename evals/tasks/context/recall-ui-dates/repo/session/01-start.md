# Earlier work in this session (state at the pause)

Decision: store dates as UTC ISO-8601 and format them only in the UI, because three services read them.

I ran `pytest tests/test_dates.py`; the last line was:
AssertionError: '07/11/2026' != '2026-11-07'

Fix: edited src/ui/dates.py: format_date renders from the stored UTC value.

The test passes now. Still open: emails/templates/receipt.html still prints the raw timestamp.

Operator: thanks, pause here. The files that follow are the tool output of the run.
