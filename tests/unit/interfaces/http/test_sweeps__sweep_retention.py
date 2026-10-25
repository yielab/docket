"""`docket start`'s periodic sweep: what it calls, in what order, and its effect.

observability/trace.py's expire_old_traces() is tested in isolation by
test_trace_retention.py. This file pins the *wiring* -- that _run_sweeps calls
sweep_all then sweep_escalations, keeps going if one raises, and runs
once at startup -- and the retention *effect* that ordering exists to protect:
expire_old_traces only ever deletes an already-terminated trace, so a
stale-but-open trace must first receive sweep_all's synthetic session_end
before expiry can consider it eligible.
"""

from __future__ import annotations

SUBJECT = "docket.interfaces.http.sweeps"
