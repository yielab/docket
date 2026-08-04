# MCP Client Specification

**Version**: 1.1.1
**Status**: Implemented. Configuration (`docket mcp servers add/list/remove`, ROADMAP Phase 19
P19-13) and the underlying adapt-and-gate machinery (`core/mcp_tools.py`,
`edges/adapters/mcp_client.py`, Phase 19 P19-10) are both shipped and CLI-reachable. **Still not
on a live agent-turn path**: `core/agent_loop.py`'s `run_agent_turn` (Phase 19 P19-5) takes an
already-built `ToolRegistry` as a caller-supplied argument rather than building one itself, so
nothing in production yet calls `load_mcp_tools` to fold a configured server's tools into that
registry before a turn starts — the same way `core/llm.py` (P19-1), `core/tools.py` (P19-2), and
`core/session.py` (P19-4) shipped ahead of their own callers. Configuring a server today makes it
inspectable (`docket mcp servers list`) and ready; it does not yet make its tools available to a
running agent.
**Last Updated**: 2026-08-04

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
- The `docket mcp servers add/list/remove` CLI (`cli/_mcp.py`, ROADMAP Phase 19 P19-13) — pure
  presentation over the configuration functions above; it validates flags and calls
  `add_mcp_server`/`load_mcp_servers`/`remove_mcp_server` unchanged
- The recipe this whole client exists to unlock: pointing docket at an off-the-shelf MCP server
  (Playwright for browser automation, any MCP-compliant search server for web search) as
  configuration rather than code — see Examples

This specification does NOT cover:

- The turn loop itself, or when/how often it calls `load_mcp_tools` (`core/agent_loop.py`,
  ROADMAP Phase 19 P19-5 — not yet built)
- `core/tools.py`'s tool schema, registry, or `dispatch_tool` chokepoint (P19-2) — this
  specification's entire premise is that none of that is touched or reimplemented; every adapted
  tool is gated by the unmodified `dispatch_tool`/`evaluate_tool_call` — see `security-gates.spec.md`
  and this module's own acceptance test (`TestGatedExactlyLikeABuiltin` in
  `tests/python/test_mcp_client.py`)
- `docket mcp serve` (docket exposing its *own* control plane as MCP tools to an external host)
  — see `mcp-server.spec.md`; that document's prior scope note describing agent-side MCP
  consumption as "a deliberately separate, unbuilt card (ROADMAP Phase 18 L-4, daemon-gated)" is
  superseded by this specification now that D-19 has docket, not a daemon, own the loop
- Non-stdio MCP transports (HTTP/SSE) — only a spawned stdio subprocess server is supported today
- Actually connecting to a configured server during a live agent turn — `docket mcp servers add`
  only writes configuration; nothing calls `load_mcp_tools` in production yet (see Status above)

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

### CLI (`docket mcp servers`)

20. `docket mcp servers list` **MUST** show every configured server's name and launch command,
    **MUST NOT** print any `env` value in the clear (mask as `KEY=****`, matching `docket keys
    list`'s masking convention), and **MUST NOT** connect to any server — it is a pure read of
    `load_mcp_servers()`.
21. `docket mcp servers add <name> [--env KEY=VALUE ...] [--timeout SECONDS] -- <command>
    [args...]` **MUST** treat everything after a literal `--` token as the server's launch command
    and arguments verbatim, so a command's own flags (e.g. `npx -y ...`) are never misparsed as
    `docket`'s own flags. `--env`/`--timeout` **MUST** be rejected with a descriptive error (exit
    1) if given after `--`, malformed, or given with no `--` present at all — a missing separator
    **MUST NOT** silently swallow the rest of the arguments as flags.
22. `docket mcp servers add` **MUST** build one `McpServerConfig` from the parsed name/command/
    args/env/timeout and pass it to `add_mcp_server` unchanged, surfacing that function's
    `ValueError` (bad/duplicate name) as a CLI error (exit 1) rather than a traceback.
23. `docket mcp servers add`/`remove` **MUST** write an audit entry (`mcp_servers.add` /
    `mcp_servers.remove`) naming the server and, for `add`, its launch command — **MUST NOT**
    record any `env` value, matching Requirement 20's masking rule for `list`. `docket mcp servers
    list` is read-only and **MUST NOT** write an audit entry.
24. None of `docket mcp servers add/list/remove` **MUST** import from, or otherwise reach,
    `core/tools.py` or any built-in tool registration — this CLI only ever calls the configuration
    functions in Requirements 1-3; connecting to a server and adapting its tools remains
    `load_mcp_tools`'s job, on whatever path eventually calls it (see Status).

## Interface Contracts

### Module API (`docket.core.mcp_tools`)

```python
NAMESPACE_PREFIX = "mcp__"

class McpServerConfig(BaseModel):              # name, command, args, env, timeout
    def resolved_timeout(self) -> float: ...   # clamped to MCP_CLIENT_MAX_TIMEOUT_S

class McpServerRegistry(BaseModel):            # servers: list[McpServerConfig]

def load_mcp_servers() -> list[McpServerConfig]: ...
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

### CLI syntax (`cli/_mcp.py`)

```
docket mcp servers list
docket mcp servers add <name> [--env KEY=VALUE ...] [--timeout SECONDS] -- <command> [args...]
docket mcp servers remove <name>
```

`add`'s `--`-separator convention (Requirement 21) is deliberate: an MCP server's own launch
command frequently carries flags of its own (`npx -y ...`, `-- --headless`, ...), and a
flag-parser that tried to distinguish "docket's flags" from "the command's flags" by position
alone would misparse the first one it saw. Everything after `--` is opaque to docket.

## Examples

### Recipe: browser support (and web search) is configuration, not code

This is the payoff decision D-19 ("rent the protocol") and decision D-24 (browser automation is on
the never-build list) both point at: docket never needed to write a Playwright wrapper, a headless
Chrome driver, or a search-API client. Pointing docket's MCP client at an existing MCP server for
that capability is a configuration step, and the client already built for P19-10 gates whatever
that server advertises exactly like a built-in tool — no new code path, no special-casing "this
tool drives a browser."

1. **Configure the server** — the [Playwright MCP server](https://github.com/microsoft/playwright-mcp)
   is a stdio MCP server that drives a real browser (navigate, click, fill forms, read the DOM,
   screenshot) and ships as an `npx` package, so nothing beyond Node (already on every agent's
   curated allowlist) is required:

   ```
   docket mcp servers add playwright -- npx -y @playwright/mcp@latest
   ```

2. **What this buys, mechanically, once something calls `load_mcp_tools`** (see Status — not yet a
   live path): every tool Playwright advertises (`browser_navigate`, `browser_click`,
   `browser_snapshot`, ...) registers as `mcp__playwright__<tool>` (Requirement 7). No amount of
   the remote server misbehaving — even a hypothetical hostile fork naming one of its own tools
   `bash` — can make `mcp__playwright__bash` collide with or shadow the real, gated `bash` tool
   (Requirement 8; see "A malicious server cannot shadow a built-in" below and
   `TestCollisionRule.test_a_malicious_server_naming_itself_after_a_builtin_tool_does_not_shadow_it`
   in `tests/python/test_mcp_client.py`). Every call — "click this button", "read this
   page" — still passes through the unmodified `dispatch_tool` chokepoint: the same
   `pre_tool_call` policy hooks, the same approval routing, the same audit trail a `bash` or `edit`
   call gets (Requirement 5; see "Gated exactly like a built-in" below).
3. **The same recipe, same reasoning, for web search**: configure any MCP-compliant search server
   (`docket mcp servers add search -- <its stdio launch command>`) and its tools register as
   `mcp__search__<tool>`, gated the same way. There is nothing browser- or search-specific in
   `core/mcp_tools.py` or `edges/adapters/mcp_client.py` — the mechanism is the transport, not the
   capability.
4. **Remove it just as cheaply** when it is no longer needed: `docket mcp servers remove
   playwright`. No code to revert, because none was written.

What this recipe deliberately does **not** do: it does not ship a Playwright wrapper, a browser
driver, or a search client anywhere in this codebase — writing one is explicitly out of scope
under decision D-24 (browser automation is on the never-build list) precisely because this
recipe makes it unnecessary. The entire "browser support" is the one `add` command above, plus
whatever server-side npm package the operator chooses to trust.

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
- `docket mcp servers add`'s parsed `command`/`args` **MUST** match exactly what followed `--` on
  the command line, in order — the CLI **MUST NOT** reorder, deduplicate, or otherwise transform
  the launch command it was given.
- `docket mcp servers list` **MUST NOT** ever cause a subprocess to be spawned — it reads
  `load_mcp_servers()` only.

### Invariants

- No adapted tool name **MUST** ever equal a built-in tool name, for any server name or remote
  tool name whatsoever (the `mcp__` prefix is unconditional).
- `list_remote_tools`/`call_remote_tool` **MUST NOT** ever propagate an exception to their caller.
- A call to an adapted tool **MUST NOT** be able to reach its underlying protocol exchange without
  first passing through `dispatch_tool`'s gate — this module holds no reference to a handler it
  did not just build for `ToolRegistry.register`, and calls the handler nowhere itself.
- `cli/_mcp.py`'s `docket mcp servers` commands **MUST NOT** import anything from `core/tools.py`
  or `edges/adapters/toolbox.py` beyond the inert `ToolOutcome` type already allowed for
  `core/mcp_tools.py` itself (see `TestOnlyTheInertResultTypeIsImported` in
  `tests/python/test_mcp_client.py`) — the CLI is configuration only, never a second
  execution path.

## Changelog

### Version 1.1.1 (2026-08-04)

- **CL-C (ROADMAP Phase 19, wave 14 dead-code sweep).** Removed
  `save_mcp_servers` from `core/mcp_tools.py` and this spec's Module API: it
  was never called by `cli/_mcp.py` or anything else (`add_mcp_server`/
  `remove_mcp_server`'s lock-safe read-modify-write are the only registry
  writers the CLI actually uses), and had no test coverage of its own. Purely
  a removal of unused surface — no behavior documented elsewhere in this spec
  changes.

### Version 1.1.0 (2026-08-02)

- **ROADMAP Phase 19, card P19-13 — `docket mcp servers` CLI.** Added `docket mcp servers
  list/add/remove` (`cli/_mcp.py`), a pure presentation layer over `add_mcp_server`/
  `load_mcp_servers`/`remove_mcp_server`, which shipped tested and uncalled in Version 1.0.0
  (P19-10). `add`'s `--`-separator syntax (Requirement 21) keeps a server's own launch flags from
  ever being misparsed as docket's. Added the `mcp_servers.add`/`mcp_servers.remove` audit action
  family (see `audit.spec.md` Version 2.4.0). Documented the recipe this client exists to unlock —
  pointing docket at the Playwright MCP server (browser automation) or any MCP-compliant search
  server, as configuration rather than code — under Examples. **Still not on a live agent-turn
  path**: this version does not change that `load_mcp_tools` has no production caller (see
  Status); configuring a server makes it inspectable and ready, not yet reachable by a running
  agent.

### Version 1.0.0 (2026-07-31)

- Initial specification: docket-owned MCP server configuration, tool enumeration and adaptation
  into `core.tools.Tool`, the `mcp__<server>__<tool>` namespacing rule that makes a built-in
  collision structurally impossible, bounded-timeout failure isolation, and `pre_input` policy
  screening of remote tool descriptions before registration (ROADMAP Phase 19 P19-10).
