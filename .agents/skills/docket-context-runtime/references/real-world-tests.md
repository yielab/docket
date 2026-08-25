# Real-world context tests

Read this for incident reproduction or RED-test design on the live turn path.

Exercise the default production caller with a scripted recording backend, a byte-observable
temporary session store, a trace sink, the real dispatcher with fake local/MCP tools, the
contract-declared configuration owner, and a deliberately small registered model window. The
backend must record complete prospective request components and distinguish task calls from
compaction calls.

Use synthetic sentinels in discarded tails and history. Assert they are absent from later requests
and traces; never put real secrets in fixtures. Observe wire requests, dispatch count/order, stored
bytes and writes, shipped `request_fit` fields, prospective request sequence, and actual backend
calls. Keep test-recorder metadata separate from the persisted trace contract. Helper return values
alone are insufficient.

Choose the dimensions implicated by evidence: later tool-loop iteration, local versus MCP output,
failed/empty/ineffective compaction, reordered or incomplete tool-call IDs, mutation of the owning
configuration surface after construction, and reducible versus irreducible fit. Assert complete
request components and state transitions, not trace prose. Always include the closest no-op/failure
case when it changes writes, transports, or atomicity.

Skill maintainers performing an independent behavioral evaluation use `forward-tests.md` as the
hidden post-run rubric. Do not give that file to the evaluated agent.
