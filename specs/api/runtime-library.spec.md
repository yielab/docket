# Runtime Library (`docket-runtime`) Contract Specification

**Version**: 2.0.0
**Status**: Implemented (artifact-tested; not published to an index)
**Last Updated**: 2026-08-31

## Purpose

`docket-runtime` is the small, embeddable part of Docket that owns a tool
registry and sends every invocation through the existing policy, approval,
audit, trace, and `core.tools.dispatch_tool` chokepoint. An embedding product
owns its serving layer and fake/real tool handlers; it does not import the
Docket CLI or reach into runtime internals.

## Scope

This contract covers package ownership, the small facade, release artifacts,
and the embedding call path. It does not add a plugin framework, server,
tenant model, alternate driver, or a public internal-module API.

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

Only these names from `docket_runtime` are public: `Runtime`, `Tool`,
`ToolCall`, `ToolContext`, `ToolOutcome`, `ToolResult`, and `__version__`.
`Runtime.register()` accepts a `Tool`; `Runtime.dispatch()` is the only facade
execution method and delegates to the preserved dispatcher chokepoint.

`Runtime(approval_stub=...)` is an embedding/test seam. It receives the token
created by the real approval store and returns whether to grant it; normal
approval audit and trace records still occur. It is not a second driver, tool
executor, or policy engine.

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
shape. Audit and trace remain durable side effects under `DOCKET_HOME`.

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

## Changelog

### Version 2.0.0 (2026-08-31)

- Replaced the overlapping `docket.*` force-included runtime artifact with the
  distinct `docket_runtime` facade and private implementation topology.
- Added standalone sdist support and the first stable embedding example.
