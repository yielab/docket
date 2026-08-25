# Evaluator-only context-runtime rubric

The evaluation coordinator may read this to prepare an isolated fixture before the run, using the
harness from `real-world-tests.md`, but must never include it in the evaluated agent's context.
Apply the required outcomes only after an independent `docket-context-runtime` candidate finishes.

## Incident matrix

| Incident | Fixture | Required observable outcome |
| --- | --- | --- |
| Overflow after a tool call | First model response requests a tool; its result makes prospective task request 2 exceed the small window | Request 2 is preflighted with tool schemas and output reserve. A reducible request sent on wire fits; an irreducible one makes no second task backend call. The recording backend proves the request sequence/call count; `request_fit` reports `purpose=task`, failed status, input estimate, reserve, window, and estimate marker without raw content |
| Oversized local and MCP results | Both tools return large JSON, Unicode, and a synthetic tail sentinel | Both cross `dispatch_tool` and use the same configured envelope/ceiling; output remains valid, truncation is visible, marker metadata obeys the owning contract, and the discarded sentinel appears nowhere model-visible or in traces |
| Compaction failure or ineffective summary | Store records exact bytes/write count; summarizer raises, returns empty, or returns a valid summary that still cannot fit | Failure/empty leaves bytes identical with zero writes and one attempted/failed trace. An accepted but insufficient summary is reloaded/rechecked once for that revision, then reduced another way or rejected locally without a compaction loop |
| Tool-call atomicity | Assistant calls IDs `a` and `b`; results arrive reversed, then a variant omits `b` at the compaction boundary | Complete requests contain each ID exactly once with its result, or contain neither unit. An incomplete unit remains visibly pending or fails locally; no orphan crosses the wire. Truncated backend responses are neither dispatched nor persisted |
| Runtime configuration change | Locate the owner named by each owning spec; construct with limit A, execute, mutate that owner to B, then reuse the same runtime objects | The next call uses B at the contract's declared resolution point without module reload. For MCP mutate `config.py`; for a built-in mutate `toolbox.MAX_OUTPUT_CHARS`. Treat owner unification as a separate RED behavior change rather than grading current local-tool behavior as wrong |

Run the focused incident first, then the owning runtime tests and additive gates from
the `docket-spec-work` skill. Grade state transitions and recorded requests, not trace wording.
