# Earlier work in this session (state at the pause)

Decision: retry with exponential backoff capped at 30 s, not a fixed 5 s, because the broker sheds load on bursts.

I ran `pytest tests/test_worker.py`; the last line was:
ConnectionResetError at worker.py line 88, exit 2 on attempt 4

Fix: edited src/queue/worker.py: the retry delay doubles per attempt up to 30 s.

The test passes now. Still open: tests/load/test_burst.py is not written yet.

Operator: thanks, pause here. The files that follow are the tool output of the run.
