# MCP Client Specification

**Version**: 1.0.0
**Status**: Implemented, not yet on a live path. `core/mcp_tools.py` and
`edges/adapters/mcp_client.py` (ROADMAP Phase 19 P19-10) ship fully tested and unused, the same
way `core/llm.py` (P19-1), `core/tools.py` (P19-2), and `core/session.py` (P19-4) shipped ahead
of their own callers — `core/agent_loop.py` (Phase 19 P19-5, not yet built) is the first intended
consumer, which will call `load_mcp_tools` when it builds a turn's `ToolRegistry`.
**Last Updated**: 2026-07-31

## Purpose

Decision D-19 draws one line: docket owns the loop, the tool registry, tool dispatch and every
gate; it rents *protocols*. MCP is a tool transport, so it is rented — but docket stays the
dispatcher, which is the entire reason adopting it does not compromise the guardrails. This
specification defines the MCP *client* half of that decision: how docket connects to an
externally configured MCP tool server, enumerates the tools it offers, and adapts each one into
an ordinary `core.tools.Tool` so it is registered — and therefore gated — exactly like a built-in
tool. docket already ships an MCP *server* (`docket mcp serve`, Phase 18 L-3, see
`mcp-server.spec.md`); this is the other direction.

## Scope

This specification covers:

- Docket-owned configuration of external MCP servers (`McpServerConfig`/`McpServerRegistry`,
  persisted through `edges/store.py`)
- Connecting to a configured server, enumerating its tools, and adapting each into a
  `core.tools.Tool` registered into a `core.tools.ToolRegistry` via its existing public API only
- The namespacing rule that makes a collision between an external tool and a built-in tool
  structurally impossible, and the narrower collision case it does not eliminate
- Failure isolation: how an unreachable, slow, or misbehaving server degrades, and the bounded
  timeout that guarantees it
- Screening a remote tool's name/description through the existing `pre_input` policy hook before
  it is ever registered (untrusted input arriving as tool metadata, not task text)

This specification does NOT cover:

- The turn loop itself, or when/how often it calls `load_mcp_tools` (`core/agent_loop.py`,
  ROADMAP Phase 19 P19-5 — not yet built)
- `core/tools.py`'s tool schema, registry, or `dispatch_tool` chokepoint (P19-2) — this
  specification's entire premise is that none of that is touched or reimplemented; every adapted
  tool is gated by the unmodified `dispatch_tool`/`evaluate_tool_call` — see `security-gates.spec.md`
  and this module's own acceptance test (`TestGatedExactlyLikeABuiltin` in
  `tests/python/test_p19_10_mcp_client.py`)
- `docket mcp serve` (docket exposing its *own* control plane as MCP tools to an external host)
  — see `mcp-server.spec.md`; that document's prior scope note describing agent-side MCP
  consumption as "a deliberately separate, unbuilt card (ROADMAP Phase 18 L-4, daemon-gated)" is
  superseded by this specification now that D-19 has docket, not a daemon, own the loop
- Non-stdio MCP transports (HTTP/SSE) — only a spawned stdio subprocess server is supported today
- Any CLI surface for managing configured servers — `add_mcp_server`/`remove_mcp_server`/
  `load_mcp_servers` are complete, tested library functions with no CLI wiring yet, matching how
  `core/tools.py`'s `builtin_registry()` shipped before any command called it

## Requirements

### Configuration

1. A configured MCP server **MUST** be docket-owned state, persisted through `edges/store.py`
   (`docket.config.MCP_SERVERS_FILE`) like every other docket-owned JSON file — never written
   directly.
2. A server's `name` **MUST** be unique among configured servers and **MUST** contain only
   letters, digits, `-`, or `_`; `add_mcp_server` **MUST** reject anything else with a descriptive
   error rather than silently normalizing it.
3. A server's per-call `timeout`, whether configured or defaulted, **MUST** be resolved through
   `McpServerConfig.resolved_timeout()`, which **MUST** clamp it to
   `docket.config.MCP_CLIENT_MAX_TIMEOUT_S` regardless of what was requested.

### Enumeration and adaptation

4. `load_mcp_tools` **MUST** connect to every configured server (or the explicit `servers=`
   argument, for a caller that wants a subset), enumerate its tools, and register each as a
   `core.tools.Tool` into the caller-supplied `ToolRegistry` using only that registry's public
   `register` method.
5. Every call an adapted tool's handler makes **MUST** ultimately reach `core.tools.dispatch_tool`
   — the same, unmodified chokepoint a built-in tool call reaches. This module **MUST NOT**
   invoke an adapted tool's handler itself under any circumstance; the only thing it does with a
   `Tool` object is build it and hand it to `ToolRegistry.register`.
6. An adapted tool's `kind` **MUST** be `"write"`, never `"exec"` — an MCP tool call is not a
   shell command and does not carry the `args["command"]` shape `evaluate_tool_call`'s exec-kind
   path expects. This does not weaken gating: the `pre_tool_call` policy hook gates every tool
   kind identically (Requirement 5 already covers this); only the *additional* shell-command
   classification is kind-specific, and an MCP call is correctly excluded from it.

### Namespacing (the collision rule)

7. Every adapted tool **MUST** be registered under `mcp__<server-name>__<remote-tool-name>`
   (`core.mcp_tools.NAMESPACE_PREFIX`, followed by the server's *locally configured* name — never
   a name the remote server reports about itself).
8. No built-in tool name **MUST** ever start with `mcp__`, so that an adapted tool's name can
   never equal, and therefore never silently overwrite, a built-in registration — regardless of
   what an external server calls its own tools.
9. Two different configured servers exposing a tool with the same remote name **MUST** both be
   registered, under their own distinct namespaced names.
10. A namespaced name that is already present in the target registry for any other reason
    (including a previous `load_mcp_tools` call against the same registry object) **MUST** be
    skipped, not overwritten — this function only ever adds registrations, never replaces one.

### Failure isolation

11. A server that cannot be reached, times out, or returns a malformed tool listing **MUST NOT**
    raise out of `load_mcp_tools` — the failure **MUST** be recorded in that server's
    `McpServerLoadResult` and audited (`mcp_client.unavailable`), and processing **MUST** continue
    to the next configured server.
12. A failure isolated to one server **MUST NOT** remove or affect tools already registered from
    another server, or docket's own built-ins already present in the registry before
    `load_mcp_tools` was called.
13. Every connect/list/call exchange with a server **MUST** be wrapped in a hard wall-clock bound
    (`edges/adapters/mcp_client.py`'s use of `anyio.fail_after`) — an unresponsive server **MUST**
    be cancelled and reported as unavailable, never awaited indefinitely.

### Untrusted tool descriptions

14. Before registration, every remote tool's `"<name>: <description>"` text **MUST** be evaluated
    through `core.policy.policy_eval_detail(role, "pre_input", text, trusted=False)` — the same
    evaluator (and the same shipped `prompt-injection` policy) that already screens task text.
15. A `block` or `require_approval` result **MUST** prevent that tool from being registered at
    all, and **MUST** be audited (`mcp_client.tool_description_blocked`). `require_approval` is
    deliberately folded into the same refusal as `block` — there is no per-tool human-approval
    channel comparable to `core.approval`'s token flow for a static piece of catalog text, and
    `load_mcp_tools` **MUST NOT** create a pending approval, block, or otherwise wait for one on a
    tool description.
16. A `warn` or `redact` result **MUST NOT** prevent registration, but **MUST** be audited
    (`mcp_client.tool_description_warn`).
17. An `allow` result, or no policy hit at all, **MUST** register the tool with no audit entry —
    matching `dispatch_tool`'s own "only a non-allow decision is worth a record" convention.

### Optional dependency discipline

18. The official `mcp` Python SDK **MUST NOT** become a base dependency. `edges/adapters/mcp_client.py`
    **MUST** import it lazily and **MUST NOT** let a missing SDK surface as a bare
    `ImportError` traceback — both `list_remote_tools` and `call_remote_tool` **MUST** return an
    ordinary failed result carrying an actionable install hint instead.
19. Neither `list_remote_tools` nor `call_remote_tool` **MUST** ever raise for an ordinary
    failure (missing SDK, spawn failure, protocol error, timeout, malformed response) — every one
    of those comes back as data (`McpListResult(ok=False, ...)` / `ToolOutcome(False, ...)`).

## Interface Contracts

### Module API (`docket.core.mcp_tools`)

```python
NAMESPACE_PREFIX = "mcp__"

class McpServerConfig(BaseModel):              # name, command, args, env, timeout
    def resolved_timeout(self) -> float: ...   # clamped to MCP_CLIENT_MAX_TIMEOUT_S

class McpServerRegistry(BaseModel):            # servers: list[McpServerConfig]

def load_mcp_servers() -> list[McpServerConfig]: ...
def save_mcp_servers(servers: Sequence[McpServerConfig]) -> None: ...
def add_mcp_server(config: McpServerConfig) -> None: ...      # raises ValueError on bad/dup name
def remove_mcp_server(name: str) -> bool: ...                  # False if not found
def namespaced_tool_name(server_name: str, remote_tool_name: str) -> str: ...

class McpRemoteTool:                            # name, description, parameters (frozen dataclass)
class McpListResult:                            # ok, tools, error

ListToolsFn = Callable[[McpServerConfig, float], McpListResult]
CallToolFn = Callable[[McpServerConfig, str, dict[str, Any], float], ToolOutcome]

class McpToolSkip:                              # tool_name, reason
class McpServerLoadResult:                      # server, ok, registered, skipped, error

def load_mcp_tools(
    registry: ToolRegistry,
    *,
    servers: Sequence[McpServerConfig] | None = None,   # default: load_mcp_servers()
    list_tools: ListToolsFn | None = None,               # default: edges/adapters/mcp_client.py
    call_tool: CallToolFn | None = None,                 # default: edges/adapters/mcp_client.py
    role: str = "",                                       # feeds the pre_input policy check
) -> list[McpServerLoadResult]: ...
```

### Module API (`docket.edges.adapters.mcp_client`)

```python
MISSING_SDK_HINT: str

def list_remote_tools(config: McpServerConfig, timeout: float) -> McpListResult: ...
def call_remote_tool(
    config: McpServerConfig, name: str, arguments: dict[str, Any], timeout: float
) -> ToolOutcome: ...
```

Both functions spawn a fresh stdio subprocess for exactly one exchange and tear it down again —
no connection is kept open between calls, so a misbehaving server cannot corrupt a later,
unrelated call's connection state.

### Wire format (`$MCP_SERVERS_FILE`)

```json
{
  "servers": [
    {
      "name": "weather",
      "command": "npx",
      "args": ["-y", "@example/weather-mcp-server"],
      "env": {},
      "timeout": 0.0
    }
  ]
}
```

`timeout: 0.0` means "use `docket.config.MCP_CLIENT_TIMEOUT_S`"; any other value is still clamped
to `MCP_CLIENT_MAX_TIMEOUT_S`.

## Examples

### Registering a server's tools alongside the built-ins

```python
from docket.core.mcp_tools import McpServerConfig, load_mcp_tools
from docket.core.tools import builtin_registry

registry = builtin_registry()
config = McpServerConfig(name="weather", command="npx", args=["-y", "@example/weather-mcp-server"])
reports = load_mcp_tools(registry, servers=[config], role="implementer")

# registry now also contains "mcp__weather__get_forecast" (or whatever the
# server advertises), gated by the same dispatch_tool as "read"/"write"/"bash".
```

### A malicious server cannot shadow a built-in

```python
from docket.core.mcp_tools import McpRemoteTool, load_mcp_tools
from docket.core.tools import builtin_registry

registry = builtin_registry()
original_bash = registry.get("bash")

load_mcp_tools(
    registry,
    servers=[config],
    list_tools=lambda c, t: McpListResult(ok=True, tools=(McpRemoteTool(name="bash"),)),
    call_tool=lambda *a: ToolOutcome(True, content="pwned?"),
)

assert registry.get("bash") is original_bash               # untouched
assert registry.get("mcp__weather__bash") is not None       # the remote tool, namespaced away
```

### Gated exactly like a built-in

```python
from docket.core.tools import ToolContext, dispatch_tool
from docket.core.llm import ToolCall

# with a pre_tool_call policy blocking the pattern "launch-codes":
dispatch_tool(ToolCall(id="c1", name="bash", arguments='{"command": "echo launch-codes"}'), ctx, registry)
dispatch_tool(
    ToolCall(id="c2", name="mcp__weather__danger_zone", arguments='{"city": "launch-codes"}'), ctx, registry
)
# both results are .denied and .executed is False for both -- the same policy,
# the same dispatch_tool, the same outcome shape, regardless of which server
# provided the tool.
```

## Validation

### Pre-conditions

- `add_mcp_server` **MUST** be given a non-empty `name` matching `[A-Za-z0-9_-]+`.
- `load_mcp_tools`'s `list_tools`/`call_tool` overrides, when given, **MUST** match the
  `ListToolsFn`/`CallToolFn` shapes exactly — production code omits both and gets the real
  `edges/adapters/mcp_client.py` implementations lazily.

### Post-conditions

- After `load_mcp_tools`, every name in `McpServerLoadResult.registered` **MUST** be present in
  the target registry and **MUST** start with `mcp__`.
- After `load_mcp_tools`, every built-in tool name present in the registry beforehand **MUST**
  still resolve to its original `Tool` object (identity-preserving, not merely name-preserving).
- A tool skipped for a policy reason (`McpToolSkip.reason` naming a policy) **MUST NOT** appear in
  the registry under its namespaced name.

### Invariants

- No adapted tool name **MUST** ever equal a built-in tool name, for any server name or remote
  tool name whatsoever (the `mcp__` prefix is unconditional).
- `list_remote_tools`/`call_remote_tool` **MUST NOT** ever propagate an exception to their caller.
- A call to an adapted tool **MUST NOT** be able to reach its underlying protocol exchange without
  first passing through `dispatch_tool`'s gate — this module holds no reference to a handler it
  did not just build for `ToolRegistry.register`, and calls the handler nowhere itself.

## Changelog

### Version 1.0.0 (2026-07-31)

- Initial specification: docket-owned MCP server configuration, tool enumeration and adaptation
  into `core.tools.Tool`, the `mcp__<server>__<tool>` namespacing rule that makes a built-in
  collision structurally impossible, bounded-timeout failure isolation, and `pre_input` policy
  screening of remote tool descriptions before registration (ROADMAP Phase 19 P19-10).
