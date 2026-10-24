# Runtime Library (`docket-runtime`) Contract Specification

**Version**: 2.3.0
**Status**: Implemented. The facade, the governed-execution envelope and two configuration-scoped adapters (OpenHands SDK, PydanticAI) ship in `docket-runtime` 0.3.0. The package is built and installed from artifacts but not published to an index.
**Last Updated**: 2026-10-23

## Purpose

`docket-runtime` is the small, embeddable part of Docket that owns a tool
registry and sends every invocation through the existing policy, approval,
audit, trace, and `dispatch_tool` chokepoint. An embedding product owns its
serving layer and fake/real tool handlers; it does not import the Docket CLI
or reach into runtime internals.

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
`docket_runtime._internal.docket`. A build hook copies a fixed list of the
runtime's modules there at wheel-build time and rewrites their first-party
absolute imports (`docket.` becomes `docket_runtime._internal.docket.`). The
list contains no CLI module. This is one source of truth, not a second
hand-maintained implementation. A missing listed source file fails the build.
`DOCKET_RUNTIME_BUILD_TMPDIR` selects the directory in which the hook stages
the copy; the staged copy is removed after the build. The runtime sdist
includes the source tree the hook reads under `runtime-source/`; rebuilding a
wheel from that sdist never relies on a parent monorepo path.

The listed modules are not import-closed. Some of them import, at module level
or lazily, modules that are not on the list (for example the pod, privacy and
secrets modules), so those listed modules fail to import inside the wheel. The
facade's own import chain resolves entirely inside the private package, and
that chain is the only supported use of it.

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
attribute. `Runtime.dispatch()` sends the call through the single tool
dispatcher and remains compatible for single-call embeddings.
`Runtime.start_execution()` creates the bounded adapter-facing envelope
described below. The additive facade requires the independent runtime package
version `0.3.0`.

`Runtime(approval_stub=...)` is an embedding/test seam. It receives the token
created by the real approval store: a true return grants it and a false return
denies it through that store without waiting. Normal approval audit and trace
records still occur, with channel `runtime`. It is not a second driver, tool
executor, or policy engine. Concurrent runtimes with different stubs MUST be
isolated: a token is answered exactly once by the stub belonging to the runtime
that dispatched that call, and the module-global approval function MUST be
restored after every success or failure. Serialization is an acceptable
implementation; cross-calling or nesting another runtime's stub is not.

## Governed execution envelope

`Runtime.start_execution(context, limits)` returns one synchronous
`GovernedExecution`. `ExecutionLimits` is frozen and carries positive
`token_budget` and `max_tool_calls` values; a non-positive value raises
`ValueError`. `TokenUsage` is the endpoint-reported
input/output/cached/cache-write-token shape also used by Docket's owned loop;
cached and cache-write tokens remain subsets of input and do not add to
`total_tokens`. The envelope accumulates input, output, cached
and cache-write tokens, so a terminal `ExecutionResult.usage` carries all four
sums.

Before dispatching any calls from one foreign model response, an adapter MUST
call `GovernedExecution.record_response(usage, tool_calls)`. The method
atomically accumulates measured usage and binds the exact ordered call batch
to that response. A `usage` that is not a `TokenUsage` raises `TypeError`. It
returns `None` when the batch is admitted, or the single terminal
`ExecutionResult` when cumulative `counted_tokens` (input minus cached tokens,
plus output, the figure the owned loop compares) is greater than the configured
budget or admitting the complete batch would exceed `max_tool_calls`; the token
check comes first.
A refused batch executes no handler and creates no pending call. Estimates
MUST NOT be accepted as `TokenUsage` or described as measured.

`GovernedExecution.dispatch(call)` accepts only the next exact call admitted
by `record_response` (id, name, and raw arguments all match). Dispatch without
a reported response, out of order, duplicate dispatch, a new response while a
prior batch is pending, or `finish` while calls remain pending raises
`RuntimeError` before policy evaluation or any durable side effect. Once a
call is admitted, malformed arguments and unknown tool names still flow
through `dispatch_tool` and return its existing fail-closed `ToolResult`; the
envelope MUST NOT implement a competing validator or invoke a handler
directly.

Every admitted dispatch emits one redacted `tool_call` trace event immediately
before the chokepoint (payload `tool`, `callId`, `arguments`) and one
`tool_result` immediately after it (payload `tool`, `callId`, `decision`, `ok`,
`executed`, plus `denialKind` when the result carries one), under
`ToolContext.project`, `session_key` and `role` as the stable execution
identity. Policy and approval audit behavior remains owned by `dispatch_tool`
and the approval store; the envelope MUST NOT duplicate audit decisions. Calls
in a batch are sequential. Each dispatched call counts toward `max_tool_calls`
except a result whose denial kind is `run_cancelled`.

`GovernedExecution.finish(summary)` terminalizes once after the last admitted
call. It returns immutable `ExecutionResult(ok=True,
stop_reason="final_message", ...)` with cumulative reported usage, admitted
tool count, output, and `HandoffArtifact(summary=summary)`. Budget refusals
return the same result type with `ok=False`, stop reason `token_budget` or
`max_tool_calls`, an `error` message, empty `output`, and a handoff with an
empty summary. After any terminal result, `record_response`, `dispatch`, and a
second `finish` raise `RuntimeError` without trace, audit, approval, or handler
side effects.

## Optional adapters

Two adapter modules ship inside the runtime wheel, outside the facade and
outside its dependencies. Importing either requires the host to install its
framework; importing `docket_runtime` does not.

`docket_runtime.adapters.openhands.OpenHandsAdapter(runtime=, context=,
limits=)` runs one OpenHands agent through `run(llm=, prompt=, workspace=,
persistence_dir=)`. It registers only the runtime's tool specs, with default
tools, skills, plugins, MCP and security-policy files disabled, one tool call
at a time. Calls to names the runtime did not advertise are not admitted. A
terminal budget result replaces the model message with the result's error text
and drops its tool calls. The run returns the terminal result, or finishes with
the last assistant text that carried no tool call.

`docket_runtime.adapters.pydantic_ai.DocketToolset(runtime=, context=,
limits=)` is one sequential PydanticAI toolset over the runtime's tool specs
with no retries. Each tool call reports the usage added since the previous
report, then dispatches the exact call. After a terminal result a later call
returns that result's error text without dispatch. Its
`finish(summary, *, usage=None)` accepts the completed run's cumulative
`RunUsage`. When supplied for an active execution, the adapter converts only
the usage since its last tool call into a final response with no tool calls
before terminalizing. That final response can therefore stop on Docket's token
budget. When a tool response already produced a terminal budget result,
`finish` returns that same result without recording later framework activity.
Omitting `usage` preserves the original embedding contract for callers that
cannot report completion usage.

## Tested adapter configurations

The installed-artifact proof covers exactly these standard configurations:

| Adapter | Pinned package | Python | Governed integration |
| --- | --- | --- | --- |
| OpenHands SDK | `openhands-sdk==1.44.1` | 3.12 | `OpenHandsAdapter` with defaults, skills, plugins, MCP, and native tools disabled |
| PydanticAI | `pydantic-ai==2.37.0` | 3.11 | One sequential `DocketToolset`, with no native or additional toolsets |

The matrix builds the `docket-runtime` wheel and sdist once, installs each
outside the checkout with both pinned fixtures, and compares normalized state,
usage, tool-call count, terminal result, handoff, trace, and audit outcomes. The
claim applies only when relevant tools are exclusively Docket-backed. ACP,
native/provider tools, plugins/MCP added beside an adapter, and arbitrary
framework configurations are outside the proof. This is not framework-neutral
compatibility.

A2A is not used because both tested adapters call the synchronous facade in
process. OTLP is not used because the existing JSONL trace preserves project,
session, role, call, and decision identity required by this proof. Neither
absence is a claim that those protocols are unsupported future work.

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
dispatch flow. No `docket` or `docket.interfaces.cli.app` import is required or supported.

## Syntax

Build both runtime artifacts from the runtime package directory with
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

`docket-runtime` is independently versioned, currently `0.3.0`; its version
does not imply a `docket` control-plane version. Before 1.0, patch releases do
not remove or change a facade name; minor releases may add facade names. A
breaking facade change requires a minor bump and a `CHANGELOG.md` entry naming the
replacement and deprecation path. At 1.0 and later, removal or signature
change requires a major bump. Private implementation modules have no
compatibility promise and must never be offered as a migration path.

## Validation

The package-boundary release test builds the wheel and sdist, installs the
sdist at the direct dependency floor outside the repository, exercises the
public facade with a policy-gated fake tool and approval stub, and proves
RECORD disjointness plus both uninstall directions. The test is the artifact
oracle; source-path inspection alone is insufficient.

The execution-envelope integration test installs a wheel and a wheel rebuilt
from the sdist into separate Python 3.11 environments outside the checkout. Its
behavioral cases cover token and tool-call preflight, exact response/call
lifecycle, paired trace identity across allow/deny/approval decisions,
malformed and unknown calls through the real chokepoint, typed terminal
handoff, concurrent approval-stub isolation, exact public exports, and
unchanged base dependencies.

The adapter-parity release test installs the same wheel and rebuilt sdist into
the pinned OpenHands SDK and PydanticAI fixture environments and compares their
normalized governed outcomes. It also proves that the base artifact imports
without either optional framework dependency. The adapter public-truth release
test checks the support boundary, protocol non-claims, and the machine-readable
compact example.

## Implementation

- `packages/docket-runtime/src/docket_runtime/__init__.py`: `Runtime`, the facade exports, `__version__`
- `packages/docket-runtime/src/docket_runtime/_execution.py`: `ExecutionLimits`, `ExecutionResult`, `GovernedExecution`
- `packages/docket-runtime/src/docket_runtime/adapters/openhands.py`: `OpenHandsAdapter`
- `packages/docket-runtime/src/docket_runtime/adapters/pydantic_ai.py`: `DocketToolset`
- `packages/docket-runtime/hatch_build.py`: the build hook and the closure it computes from the facade's import-time imports (`runtime_closure`), `DOCKET_RUNTIME_BUILD_TMPDIR`
- `packages/docket-runtime/pyproject.toml`: package version, dependency floors, sdist `runtime-source/` force-include
- `src/docket/agent/tools/registry.py`: `dispatch_tool`, `Tool`, `ToolContext`, `ToolResult`, `ToolRegistry.specs`
- `src/docket/agent/ports.py`: `TokenUsage` (`total_tokens`, `counted_tokens`), `ToolCall`, `ToolSpec`, the `ToolGate` port
- `src/docket/governance/gate.py`: `govern`, the gate `dispatch_tool` asks through that port (bound by `_bind.py`)
- `src/docket/governance/approval.py`: the approval store the stub answers
- `src/docket/observability/trace.py`: `trace_event`
- `src/docket/kernel/handoff.py`: `HandoffArtifact`
- `src/docket/agent/tools/builtins/toolbox.py`: `ToolOutcome`
- `tests/agent/release/test_runtime_package_boundary.py`: artifact boundary oracle
- `tests/agent/release/test_runtime_adapter_parity.py`, `tests/agent/release/test_runtime_openhands_adapter.py`: adapter parity
- `tests/agent/release/test_runtime_adapter_public_truth.py`: support boundary and protocol non-claims
- `tests/integration/test_runtime_execution_envelope.py`: envelope behaviour
