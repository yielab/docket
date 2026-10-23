"""Pod pipeline dispatch: drives queued tasks through lead -> implementer -> reviewer -> tester,
one real agent turn per present role, with a trace event and budget check per hop. Always within
a single pod; invoked only by an explicit trigger or the opt-in ``serve --dispatch`` loop.
Behavioral contract: specs/functional/pod-dispatch.spec.md (claiming, crash recovery, retries,
timeouts, budget/auto-pause, require_approval/``waiting_approval``, verify/verdict/PASS-FAIL
gates) and specs/functional/security-gates.spec.md (``pre_input``/``pre_output``/``pre_tool_call``).
Load-bearing points not obvious from either: a ``claimId`` is identifying only -- the concurrency
guarantee is the filelock held for the whole claim read-modify-write, never a claimId comparison.
``pre_input`` fires once at enqueue, not per hop, so incoming text cannot re-trip a ``"*"``-scoped
policy at every role. ``pod_gating_cost``'s token estimate is gating-only, never recorded spend
(the driver can report ``cost_usd = 0.0``).
"""

from __future__ import annotations


# A "dispatch every pod in one sweep" helper doesn't exist here on purpose —
# not an oversight. `serve.py`'s sweep loop instead iterates
# `dispatchable_pods()` and calls `dispatch_pod()` per pod through
# `core.runs.execute` (see `tests/guards/test_no_suppressed_dispatch.py`).
# A single-sweep helper's natural shape — one record for the whole sweep,
# catching and swallowing `DispatchError` per pod — loses per-pod granularity
# in the run registry (one run id per pod) and hides a real error instead of
# surfacing it. Do not reintroduce that shape.
