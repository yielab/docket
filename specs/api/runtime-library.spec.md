# Runtime Library (`docket-runtime`) Contract Specification

**Version**: 2.1.0
**Status**: Implemented artifact facade; W28-C1 governed-execution envelope specified with RED
tests and pending production implementation (not published to an index)
**Last Updated**: 2026-09-01

## Purpose

`docket-runtime` is the small, embeddable part of Docket that owns a tool
registry and sends every invocation through the existing policy, approval,
audit, trace, and `core.tools.dispatch_tool` chokepoint. An embedding product
owns its serving layer and fake/real tool handlers; it does not import the
Docket CLI or reach into runtime internals.

## Scope

This contract covers package ownership, the small facade, release artifacts,
the embedding call path, and the synchronous governed-execution envelope used
by external-runtime adapters. It does not add a plugin framework, server,
tenant model, alternate driver, public agent loop, or a public internal-module
API.

## Ownership topology

The full `docket` distribution exclusively owns the `docket/` import tree.
`docket-runtime` exclusively owns `docket_runtime/`. Their wheel `RECORD`
paths are disjoint, so both wheels may be installed in either order and either
may be uninstalled without deleting files required by the other.

The runtime wheel contains a private implementation at
`docket_runtime._internal.docket`. `packages/docket-runtime/hatch_build.py`
copies the measured, CLI-free runtime closure there at build time and rewrites
its first-party absolute imports. This is one source of truth, not a second
hand-maintained implementation. The runtime sdist includes the build source
under `runtime-source/`; rebuilding a wheel from that sdist never relies on a
parent monorepo path.

Private modules are implementation detail and are not a supported import path.
The runtime package has exactly two direct dependencies: `pydantic>=2.1` and
`filelock>=3.13`. Its sdist and wheel must install against the lowest direct
resolution of those floors.

## Public facade

Only these names from `docket_runtime` are public: `ExecutionLimits`,
`ExecutionResult`, `GovernedExecution`, `HandoffArtifact`, `Runtime`, `Tool`,
`ToolCall`, `ToolContext`, `ToolOutcome`, `ToolResult`, `ToolSpec`,
`TokenUsage`, and `__version__`. `Runtime.register()` accepts a `Tool`, while
`Runtime.tool_specs()` returns an immutable, name-sorted tuple of handler-free
`ToolSpec` advertisements for an adapter to translate. The mutable registry
and handlers remain private and are not reachable through a public runtime
attribute. `Runtime.dispatch()` delegates to the preserved dispatcher
chokepoint and remains compatible for single-call embeddings.
`Runtime.start_execution()` creates the bounded adapter-facing envelope
described below. The additive facade requires the independent runtime package
version `0.3.0`.

`Runtime(approval_stub=...)` is an embedding/test seam. It receives the token
created by the real approval store: a true return grants it and a false return
denies it through that store without waiting. Normal approval audit and trace
records still occur. It is not a second driver, tool executor, or policy
engine. Concurrent runtimes with different stubs MUST be isolated: a token is
answered exactly once by the stub belonging to the runtime that dispatched
that call, and the module-global approval function MUST be restored after
every success or failure. Serialization is an acceptable implementation;
cross-calling or nesting another runtime's stub is not.

## Governed execution envelope

`Runtime.start_execution(context, limits)` returns one synchronous
`GovernedExecution`. `ExecutionLimits` is frozen and carries positive
`token_budget` and `max_tool_calls` values. `TokenUsage` is the endpoint-
reported input/output/cached-token shape already used by Docket's owned loop;
cached tokens remain a subset of input and do not add to `total_tokens`.

Before dispatching any calls from one foreign model response, an adapter MUST
call `GovernedExecution.record_response(usage, tool_calls)`. The method
atomically accumulates measured usage and binds the exact ordered call batch
to that response. It returns `None` when the batch is admitted, or the single
terminal `ExecutionResult` when cumulative `total_tokens` is greater than the
configured budget or admitting the complete batch would exceed
`max_tool_calls`. A refused batch executes no handler and creates no pending
call. Estimates MUST NOT be accepted as `TokenUsage` or described as measured.

`GovernedExecution.dispatch(call)` accepts only the next exact call admitted
by `record_response` (id, name, and raw arguments all match). Dispatch without
a reported response, out of order, duplicate dispatch, a new response while a
prior batch is pending, or `finish` while calls remain pending raises
`RuntimeError` before policy evaluation or any durable side effect. Once a
call is admitted, malformed arguments and unknown tool names still flow
through `core.tools.dispatch_tool` and return its existing fail-closed
`ToolResult`; the envelope MUST NOT implement a competing validator or invoke
a handler directly.

Every admitted dispatch emits one redacted `tool_call` immediately before the
chokepoint and one `tool_result` immediately after it, using
`ToolContext.project`, `session_key`, and `role` as the stable execution
identity and the loop's existing bounded payload fields. Policy and approval
audit behavior remains owned by `dispatch_tool` and the approval store; the
envelope MUST NOT duplicate audit decisions. Calls in a batch are sequential,
and the cumulative count follows the owned loop's admission semantics.

`GovernedExecution.finish(summary)` terminalizes once after the last admitted
call. It returns immutable `ExecutionResult(ok=True,
stop_reason="final_message", ...)` with cumulative reported usage, admitted
tool count, output, and `HandoffArtifact(summary=summary)`. Budget refusals
return the same result type with `ok=False`, stop reason `token_budget` or
`max_tool_calls`, no output mutation, and a minimum empty-summary handoff.
After any terminal result, `record_response`, `dispatch`, and a second
`finish` raise `RuntimeError` without trace, audit, approval, or handler side
effects.

### Example

```python
from docket_runtime import Runtime, Tool, ToolCall, ToolContext, ToolOutcome

runtime = Runtime(approval_stub=lambda token: True)
runtime.register(Tool(
    "fake", "example", {"type": "object"},
    lambda args, ctx: ToolOutcome(True, "ran"),
))
result = runtime.dispatch(
    ToolCall("call-1", "fake", "{}"),
    ToolContext(agent_id="embed", project="demo"),
)
assert result.ok
```

An embedding may place a `pre_tool_call` policy under `DOCKET_HOME/policies`.
The example's call then follows the normal policy -> approval -> audit/trace ->
dispatch flow. No `docket` or `docket.cli` import is required or supported.

## Syntax

Build both runtime artifacts from `packages/docket-runtime` with
`uv build --out-dir dist`. Install either artifact in a clean environment with
its direct dependency floor, then import only `docket_runtime` as in the
example above.

## Arguments

Not applicable: this is a library facade, not a command.

## Options

Not applicable. `Runtime.approval_stub` is an explicit constructor seam for an
embedding or test host, not a package or CLI option.

## Output

`Runtime.dispatch()` returns `ToolResult`. The handler's successful content,
or the gate's denial/approval result, remains represented by that existing
shape. `GovernedExecution.dispatch()` returns that same `ToolResult` while
`record_response()` and `finish()` expose the typed terminal result described
above. Audit and trace remain durable side effects under `DOCKET_HOME`.

## Return

Building or installing follows the build frontend's exit convention. Facade
dispatch never bypasses the existing `ToolResult` return contract.

## Versioning and deprecation

`docket-runtime` is independently versioned, currently `0.2.0`; its version
does not imply a `docket` control-plane version. Before 1.0, patch releases do
not remove or change a facade name; minor releases may add facade names. A
breaking facade change requires a minor bump and a changelog entry naming the
replacement and deprecation path. At 1.0 and later, removal or signature
change requires a major bump. Private implementation modules have no
compatibility promise and must never be offered as a migration path.

## Validation

`tests/python/test_runtime_package_boundary.py` builds the wheel and sdist,
installs the sdist at the direct dependency floor outside the repository,
exercises the public facade with a policy-gated fake tool and approval stub,
and proves RECORD disjointness plus both uninstall directions. The test is the
artifact oracle; source-path inspection alone is insufficient.

`tests/python/test_runtime_execution_envelope.py` installs a wheel and a wheel
rebuilt from the sdist into separate Python 3.11 environments outside the
checkout. Its behavioral cases cover token and tool-call preflight, exact
response/call lifecycle, paired trace identity across allow/deny/approval
decisions, malformed and unknown calls through the real chokepoint, typed
terminal handoff, concurrent approval-stub isolation, exact public exports,
and unchanged base dependencies.

## Changelog

### Version 2.1.0 (2026-09-01)

- W28-C1 specifies the first external-runtime execution envelope: exact
  response/call admission, endpoint-reported token and tool-call budgets before
  mutation, the existing dispatch chokepoint and paired traces, isolated real-
  store approval stubs, and one typed terminal result/handoff. The artifact
  RED suite pins the missing behavior before production implementation.

### Version 2.0.0 (2026-08-31)

- Replaced the overlapping `docket.*` force-included runtime artifact with the
  distinct `docket_runtime` facade and private implementation topology.
- Added standalone sdist support and the first stable embedding example.
