# MCP Client Specification

**Version**: 1.6.0
**Status**: Implemented, and **wired to the live turn path** (ROADMAP Phase 19/wave 17). Docket's
oldest recorded known-true limit — "MCP tools are NOT reachable in a live turn" — is closed.
`edges/adapters/docket_runtime.py`'s `DocketDriver` gained a second injection seam, `mcp_loader`
(defaulting to a thin wrapper over :func:`load_mcp_tools`), called from `run_turn` right after the
turn's registry is built (`registry_factory()`) and before `core/agent_loop.py`'s `run_agent_turn`
narrows it by role — so every configured server's tools are both *reachable* by a running agent
and *subject to the same per-role narrowing a built-in tool gets*. Configuring a server
(`docket mcp servers add`) now makes its tools available on the very next turn, no restart or
separate activation step needed. See "Requirement 25-28" below for the wiring contract and
`role-archetypes.spec.md`'s new requirement 6 for the role-narrowing half this depended on: a
naive wire (add MCP tools before narrowing, without also excluding by `Tool.kind`) would have
silently defeated a Reviewer's "no write/edit/bash" guarantee, since a namespaced MCP tool name
(`mcp__<server>__<tool>`) can never equal a literal denied name. That gap is closed, not merely
avoided by omission — see the Version 1.2.0 changelog entry below ("The blocking design question").
**Phase 27, P27-3 (2026-09-26): a server now declares its own kind.** `McpServerConfig` gained
`kind: Literal["read","write"] = "write"` and `tools: list[str] = []` (empty = all) — an operator
assertion, not a proof: docket still cannot verify a remote tool is actually read-only, but an
operator who configures a genuinely read-only server (a search/fetch server with no mutating
tool) can now say so, and `_build_tool` registers every one of that server's adapted tools with
the declared `kind` instead of the unconditional `"write"` 1.1.0 shipped. Because
`registry_for_role` already excludes by `Tool.kind` (`role-archetypes.spec.md` requirement 6), a
`kind: read` server's tools now reach a role whose `denied_tools` implies only `write`/`exec` —
no change to `core/archetypes.py` needed. `tools` narrows registration to a named subset of a
server's advertised tools (every other tool is skipped with a reason); leaving it empty keeps
today's "register everything" behavior. An existing `docket-mcp-servers.json` written before this
version has neither key and loads unchanged (`kind` defaults to `"write"`, `tools` to `[]`), so a
pre-1.5.0 install's behavior does not change until an operator opts in. See Requirements 6 and
32-33.
**What remains unwired, stated plainly:** no per-turn caching of a server's tool listing (every
turn that reaches a configured server re-spawns it — see the Version 1.2.0 changelog entry's measured per-turn cost and its
named trigger for when to add one); HTTP/SSE transports remain unsupported (stdio only, unchanged
scope); **per-tool** trust/capability metadata still does not exist — `kind`/`tools` are declared
once per *server*, so a server that mixes read and mutating tools still cannot be split finer than
"trust none of it" (leave `kind` at the default `write`) or "trust all of it" (`kind: read`); a
role that denies `write` gets zero tools from a mixed server exactly as before, and docket still
cannot verify an operator's `kind: read` assertion is true. Remote tool results use the same live
`DOCKET_TOOL_MAX_OUTPUT_CHARS` ceiling as built-ins, resolved for every call so a small-context
endpoint cannot be bypassed through MCP output.
**Last Updated**: 2026-09-26

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
- **`DocketDriver.run_turn`'s `mcp_loader` seam** (`edges/adapters/docket_runtime.py`) — the call
  site that makes a configured server's tools reachable by a running agent, and the ordering
  guarantee (loaded before role narrowing) that keeps that reachability compatible with
  `role-archetypes.spec.md`'s per-role tool sets
- The model-visible output ceiling for a remote tool result, including visible truncation and
  per-call resolution of `docket.config.TOOL_MAX_OUTPUT_CHARS`

This specification does NOT cover:

- `core/tools.py`'s tool schema, registry, or `dispatch_tool` chokepoint (P19-2) — this
  specification's entire premise is that none of that is touched or reimplemented; every adapted
  tool is gated by the unmodified `dispatch_tool`/`evaluate_tool_call` — see `security-gates.spec.md`
  and this module's own acceptance test (`TestGatedExactlyLikeABuiltin` in
  `tests/integration/test_mcp_client.py`)
- `docket mcp serve` (docket exposing its *own* control plane as MCP tools to an external host)
  — see `mcp-server.spec.md`; that document's prior scope note describing agent-side MCP
  consumption as "a deliberately separate, unbuilt card (ROADMAP Phase 18 L-4, daemon-gated)" is
  superseded by this specification now that D-19 has docket, not a daemon, own the loop
- Non-stdio MCP transports (HTTP/SSE) — only a spawned stdio subprocess server is supported today
- **The role-narrowing mechanism itself** (`core.archetypes.registry_for_role`'s kind-based
  exclusion) — this specification only documents that `DocketDriver` loads MCP tools *before* that
  narrowing runs, and why that ordering matters; `role-archetypes.spec.md` owns the narrowing
  contract
- **Per-turn caching of a server's tool listing** — not built; every turn that reaches a
  configured server re-spawns it (see Status above for the measured cost and named trigger)
- **Per-tool trust/capability metadata** — a whole server can be declared `kind: read` (P27-3,
  Requirement 6), but there is still no way to mark one specific tool on a mixed server as
  read-only; a role that denies `write` gets zero tools from a server left at the default `write`
  kind, whole-server, not a correctly-narrowed per-tool subset (see Status above)
- **Proving a `kind: read` declaration true** — `kind` is an operator assertion recorded at
  configuration time; nothing here connects to a server and inspects what its tools actually do

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
6. An adapted tool's `kind` **MUST** be its server's declared `McpServerConfig.kind`
   (`"read"` or `"write"`, defaulting to `"write"` when a config predates this field), never
   `"exec"` — an MCP tool call is not a
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
    and arguments verbatim, so a command's own flags (e.g. `npx -y ...`, or a `--env`/`--timeout`
    that belongs to the launched process rather than to `docket`) are never misparsed as `docket`'s
    own flags. `--env`/`--timeout` given *before* `--` **MUST** be rejected with a descriptive
    error (exit 1) if malformed, or if no `--` is present at all — a missing separator **MUST NOT**
    silently swallow the rest of the arguments as flags. This holds across the real CLI entry
    point (`docket mcp servers add ...`), not only when `--` has already been split out of the
    argument list before reaching `cli/_mcp.py`.
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
    `load_mcp_tools`'s job, called by `DocketDriver.run_turn` (Requirement 25).

### Live-turn wiring (ROADMAP Phase 19/wave 17)

25. `edges/adapters/docket_runtime.py`'s `DocketDriver` **MUST** expose an `mcp_loader` seam
    (`Callable[[ToolRegistry, str, str], list[McpServerLoadResult]]` — registry, role, project),
    defaulting to a thin wrapper around `load_mcp_tools`, so a test can substitute a fake
    `list_tools`/`call_tool` pair (per Requirement 4's own port) without spawning a subprocess or
    requiring the `mcp` SDK.
26. `DocketDriver.run_turn` **MUST** call `self.mcp_loader(registry, role, ctx.project)` against
    the registry returned by `self.registry_factory()` (typically `core.tools.builtin_registry()`)
    **before** that registry is handed to `core.agent_loop.run_agent_turn` — i.e. before
    `core.archetypes.registry_for_role`'s once-per-turn narrowing runs (`agent-loop.spec.md`).
    This ordering **MUST NOT** be reversed: narrowing after loading is what lets
    `role-archetypes.spec.md`'s requirement 6 (kind-based exclusion) see, and exclude, an
    MCP-adapted tool for a role that denies the capability it represents.
27. A zero-server install (`load_mcp_servers()` returns `[]`, the default for any install that has
    never run `docket mcp servers add`) **MUST** produce a registry, a system prompt, and a set of
    tool advertisements to the model **byte-for-byte identical** to the pre-wave-17 behavior (no
    call to `load_mcp_tools` at all). `load_mcp_tools` with zero servers **MUST NOT** mutate the
    registry, write an audit entry, or spawn a subprocess.
28. Nothing in `DocketDriver.run_turn`'s use of `mcp_loader` **MUST** change `run_agent_turn`'s own
    "never raises for an ordinary failure" contract (`agent-loop.spec.md`) — `load_mcp_tools`
    already never raises (Requirement 11-13, 19), so a server that is unreachable, hung (bounded by
    Requirement 13's timeout), or returns a malformed listing degrades to "unavailable" and the
    turn proceeds on whatever registry resulted, never failing solely because of MCP loading. The
    one deliberate exception is Requirement 34's pod-scoped selection: a caller misconfiguration,
    not a live-server failure, so it raises instead of degrading.
29. This specification does not itself define a caching layer for `load_mcp_tools`'s per-turn
    cost — see Status above for the measured latency and the named trigger for adding one. Any
    future cache **MUST** invalidate on a `docket mcp servers remove`/`add`/edit, not merely on a
    TTL — a stale cache that resurrects a removed server's tool is a correctness bug, not a
    performance tradeoff.

### Pod-scoped server selection (P27-4)

34. `edges/adapters/docket_runtime.py::_load_mcp_tools(registry, role, project)` **MUST** filter
    `load_mcp_servers(project)`'s catalog (global servers plus *project*'s pod-scoped ones,
    Requirements 37-38) by *project*'s pod `mcpServers` setting
    (`core.pod.PodSettings.mcp_servers`, `pod-dispatch.spec.md`'s "Pod dispatch settings" item 7)
    before calling `load_mcp_tools`. `None` — the default, and every project before this setting
    existed — **MUST** load every configured server, byte-for-byte identical to Requirement 27's
    zero-server fast path and to every dispatch before this card. A selection naming a server
    absent from the *live* catalog **MUST** raise `DispatchError` naming it, instead of silently
    loading the remaining servers or none at all — a stale selection (the server was renamed or
    removed after `config set`) **MUST** be loud. This re-check runs on every read (through
    `PodSettings.coerce`, not `PodSettings.load_for`, so an unrelated malformed pod setting never
    blocks MCP loading — see `pod-dispatch.spec.md` item 7), not only at `config set` time.

### Model-visible output bound

30. `call_remote_tool` **MUST** visibly truncate rendered remote output at
    `docket.config.TOOL_MAX_OUTPUT_CHARS`, the same operator-controlled context ceiling used by
    built-in tools. The marker **MUST** report how many characters were omitted.
31. The adapter **MUST** resolve `TOOL_MAX_OUTPUT_CHARS` on every call, not copy it into a module
    constant or default argument at import time. Changing the configured value after import
    **MUST** affect the next remote tool result.

### Declared kind and tool subset (P27-3)

32. `McpServerConfig` **MUST** carry `kind: Literal["read", "write"] = "write"` and
    `tools: list[str] = []`. Both are operator assertions validated at write time by
    `add_mcp_server` (a `kind` outside `{"read", "write"}` **MUST** raise `ValueError`, surfaced by
    the CLI as an exit-1 error naming the field, per Requirement 22); neither is ever inferred by
    connecting to the server. An empty `tools` list means "every tool the server advertises";
    a non-empty one is the exhaustive allow-list of remote tool names `load_mcp_tools` **MUST**
    register — every other advertised tool **MUST** be recorded in that server's
    `McpServerLoadResult.skipped` with an `McpToolSkip` reason naming that it is "not in the
    server's `tools` list", exactly like Requirement 10's existing collision-skip, never silently
    dropped. Reading a `docket-mcp-servers.json` written before this version (neither key present)
    **MUST** produce `kind="write", tools=[]` — today's behavior — unchanged.
33. The load outcome `load_mcp_tools` returns for each server **MUST** name that server's declared
    `kind`, so an operator (or an audit trail reader) can see which trust level a given load ran
    under without re-reading the config file.

### Pod-scoped servers (recipe-declared)

37. A server declared by a recipe **MUST** be stored under its pod, in
    `config.pod_config_dir(project)/mcp-servers.json` (the `McpServerRegistry` shape), written
    through `edges/store.py`. `load_mcp_servers(project)` **MUST** return the global servers
    followed by that pod's own; `load_mcp_servers()` with no project **MUST** stay global-only.
    A pod-scoped name equal to a global name **MUST** be refused at apply, never shadowed. The
    live turn (`_load_mcp_tools`) **MUST** load a pod's own servers for that pod only.
38. `PodSettings` `mcpServers` **MUST** accept a global name or a name in this pod's own
    pod-scoped file, and **MUST** refuse any other name; a name that belongs to another pod
    **MUST** be refused with an error saying so. Nothing installs a pod-scoped server except
    `docket pod <p> apply` (ADR 0012): `validate`, `apply --dry-run`, `init --no-apply` and
    dispatch write nothing.

### Turn root for stdio servers

39. A stdio server spawned for a live turn **MUST** start in that turn's resolved root: the same
    `ctx.roots[0]` the built-in file tools are confined to (the task worktree, else the codebase,
    else the workspace). `DocketDriver.run_turn` **MUST** pass it to `mcp_loader` as the `cwd`
    keyword; `load_mcp_tools(..., cwd=)` **MUST** carry it to every listing and adapted call
    (`list_remote_tools`/`call_remote_tool(..., cwd=)`, then `_stdio_params(config, cwd)`). It is
    a runtime argument and **MUST NOT** be stored in `McpServerConfig` or any document. A caller
    outside a turn (`docket mcp servers test`, `config explain`, listing) passes none and the
    server inherits the process's directory, as before. With `cwd` absent `_load_mcp_tools`
    **MUST** call `load_mcp_tools` exactly as before.

### Untrusted tool results

35. The text of a remote tool's result **MUST** be evaluated, inside the adapted tool's handler,
    through `core.policy.policy_eval_detail(ctx.role, "pre_input", text, trusted=False)`; *text*
    is the outcome's `content` when it succeeded and its `error` when it did not. A result with
    no text **MUST** pass unchanged and unaudited.
36. A `block` or `require_approval` result **MUST** replace the outcome with `ok=False` whose
    error names the server and the policy id (never the result text), and **MUST** be audited
    (`mcp_client.tool_result_blocked`, naming server, tool, policy and action). A `redact`
    result **MUST** return the text passed through `core.trace.redact`, and a `warn` result
    **MUST** return it unchanged; both **MUST** be audited (`mcp_client.tool_result_warn`).
    `allow`, or no hit, passes the outcome byte-identical with no audit entry. Built-in tool
    results and `fetch` are out of scope.

## Interface Contracts

### Module API (`docket.core.mcp_tools`)

```python
NAMESPACE_PREFIX = "mcp__"

class McpServerConfig(BaseModel):              # name, command, args, env, timeout, kind, tools
    def resolved_timeout(self) -> float: ...   # clamped to MCP_CLIENT_MAX_TIMEOUT_S
    # kind: Literal["read", "write"] = "write" -- declared trust level, an operator
    #   assertion (Requirement 32), never inferred by connecting to the server
    # tools: list[str] = []                    -- non-empty = exhaustive allow-list of
    #   remote tool names to register; empty = register everything advertised

class McpServerRegistry(BaseModel):            # servers: list[McpServerConfig]

def load_mcp_servers() -> list[McpServerConfig]: ...
def add_mcp_server(config: McpServerConfig) -> None: ...      # raises ValueError on bad/dup name,
                                                                 #   or a kind outside read|write
def remove_mcp_server(name: str) -> bool: ...                  # False if not found
def namespaced_tool_name(server_name: str, remote_tool_name: str) -> str: ...

class McpRemoteTool:                            # name, description, parameters (frozen dataclass)
class McpListResult:                            # ok, tools, error

ListToolsFn = Callable[[McpServerConfig, float], McpListResult]
CallToolFn = Callable[[McpServerConfig, str, dict[str, Any], float], ToolOutcome]

class McpToolSkip:                              # tool_name, reason
class McpServerLoadResult:                      # server, ok, kind, registered, skipped, error

def load_mcp_tools(
    registry: ToolRegistry,
    *,
    servers: Sequence[McpServerConfig] | None = None,   # default: load_mcp_servers()
    list_tools: ListToolsFn | None = None,               # default: edges/adapters/mcp_client.py
    call_tool: CallToolFn | None = None,                 # default: edges/adapters/mcp_client.py
    role: str = "",                                       # feeds the pre_input policy check
    cwd: str | None = None,                               # stdio servers start here (Requirement 39)
) -> list[McpServerLoadResult]: ...
```

### Module API (`docket.edges.adapters.mcp_client`)

```python
MISSING_SDK_HINT: str

def list_remote_tools(config: McpServerConfig, timeout: float, cwd: str | None = None) -> McpListResult: ...
def call_remote_tool(
    config: McpServerConfig, name: str, arguments: dict[str, Any], timeout: float,
    cwd: str | None = None,
) -> ToolOutcome: ...
```

### `DocketDriver`'s wiring seam (`docket.edges.adapters.docket_runtime`)

```python
@dataclass
class DocketDriver:
    backend_factory: Callable[[str], ChatBackend | None] = client_for
    registry_factory: Callable[[], ToolRegistry] = builtin_registry
    mcp_loader: Callable[..., list[Any]] = _load_mcp_tools  # (registry, role, project, *, cwd=None)

    def run_turn(self, agent_id: str, session_key: str, message: str, ...) -> TurnResult:
        ...
        registry = self.registry_factory()
        self.mcp_loader(registry, meta.role, ctx.project, cwd=str(ctx.roots[0]))   # folds MCP tools in, before role narrowing
        ...
        result = _loop.run_agent_turn(backend, registry, ctx, session_key, message, config=loop_config)
```

`mcp_loader`'s three-positional shape (`registry`, `role`, `project`) is a fixed wrapper around
`load_mcp_tools`'s keyword-heavy signature (Module API above) so a test can substitute a fake
without matching that full surface — see Requirement 25. `project` is what Requirement 34's
pod-scoped `mcpServers` filtering keys off.

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
      "timeout": 0.0,
      "kind": "write",
      "tools": []
    }
  ]
}
```

`timeout: 0.0` means "use `docket.config.MCP_CLIENT_TIMEOUT_S`"; any other value is still clamped
to `MCP_CLIENT_MAX_TIMEOUT_S`. `kind`/`tools` are optional on read (Requirement 32): a file written
before P27-3 has neither key and loads as `kind="write", tools=[]`.

### CLI syntax (`cli/_mcp.py`)

```
docket mcp servers list
docket mcp servers add <name> [--env KEY=VALUE ...] [--timeout SECONDS]
    [--kind read|write] [--tools NAME,NAME,...] -- <command> [args...]
docket mcp servers remove <name>
```

`--kind`/`--tools` follow the same before-`--` convention as `--env`/`--timeout` (Requirement 21);
an invalid `--kind` value exits 1 naming the field rather than reaching `add_mcp_server`'s own
`ValueError` path. `--tools` takes a single comma-separated argument (no repeated flag, unlike
`--env`) since it names a subset of one server's own tools, not a set of independent key/value
pairs.

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

2. **What this buys, mechanically, once `DocketDriver.run_turn` calls `load_mcp_tools`** (see
   Status and Requirements 25-28 — the live turn path since wave 17): every tool Playwright advertises (`browser_navigate`, `browser_click`,
   `browser_snapshot`, ...) registers as `mcp__playwright__<tool>` (Requirement 7). No amount of
   the remote server misbehaving — even a hypothetical hostile fork naming one of its own tools
   `bash` — can make `mcp__playwright__bash` collide with or shadow the real, gated `bash` tool
   (Requirement 8; see "A malicious server cannot shadow a built-in" below and
   `TestCollisionRule.test_a_malicious_server_naming_itself_after_a_builtin_tool_does_not_shadow_it`
   in `tests/integration/test_mcp_client.py`). Every call — "click this button", "read this
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
- With zero configured servers, `DocketDriver.run_turn`'s registry, the tool specs advertised to
  the model, and every downstream effect **MUST** be identical to a `DocketDriver` built before
  this version — proven by `tests/unit/core/test_mcp_tools.py::
  TestZeroServersIsUnchanged`, not merely asserted.
- A role whose `denied_tools` implies kind `write` (every archetype that denies `write`/`edit`)
  **MUST NOT** be advertised, and **MUST NOT** be able to dispatch, any MCP-adapted tool — proven
  end-to-end through `DocketDriver.run_turn` (not only at `registry_for_role`'s own level) by
  `tests/unit/core/test_mcp_tools.py::TestReviewerNeverGainsAWriteCapableMcpTool`.

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
  `tests/integration/test_mcp_client.py`) — the CLI is configuration only, never a second
  execution path.
- A failure isolated to `DocketDriver.mcp_loader` (an unreachable, hung, or malformed-listing
  server) **MUST NOT** cause `run_turn` to return `ok=False` on its own — only an otherwise-real
  turn failure (backend error, timeout, budget) may do that (Requirement 28).
- A pod's stale `mcpServers` selection (Requirement 34) is not this kind of failure: it **MUST**
  raise `DispatchError` out of `run_turn` rather than folding into a `TurnResult(ok=False, ...)` —
  a caller misconfiguration surfaces to its caller's own settle/fail path (`pod-dispatch.spec.md`),
  never as an ordinary turn outcome.

## Changelog

### Unreleased

- Requirement 39 added: a stdio server spawned for a turn starts in that turn's resolved root; `mcp_loader` gains a `cwd` keyword.

- Requirements 37-38 added: a recipe may declare pod-scoped MCP servers (`mcp-servers/*.yaml`,
  `kind: mcp-server`), installed only by `docket pod <p> apply`, selectable by that pod only.

- Requirements 35-36 added: a remote tool's result is screened through `pre_input` as untrusted
  input (block/redact/warn), audited as `mcp_client.tool_result_blocked`/`_warn`.

### Version 1.6.0 (2026-09-26)

- **P27-4: a pod can select which configured MCP servers reach its turns.** New "Pod-scoped
  server selection" requirement 34: `_load_mcp_tools` gains a `project` parameter and filters
  `load_mcp_servers()`'s catalog by that pod's `mcpServers` setting (`pod-dispatch.spec.md`'s
  "Pod dispatch settings" item 7) before folding servers in; `None` (unset) loads every server,
  unchanged from every dispatch before this card. A stale selection (naming a server no longer
  in the catalog) raises `DispatchError` naming it rather than silently narrowing further or
  loading nothing — the one deliberate exception to Requirement 28's "never raises" contract,
  since this is a caller misconfiguration, not a live-server failure. Requirements 25/26 and the
  `DocketDriver` wiring-seam Interface Contract are reworded for `mcp_loader`'s new three-
  positional shape (`registry`, `role`, `project`).

### Version 1.5.0 (2026-09-26)

- Requirements 32-33 added: `McpServerConfig` gains `kind: read|write` (default `write`, an
  operator assertion never inferred from the server) and `tools` (an allow-list; empty means every
  advertised tool). `_build_tool` registers each adapted tool with the server's declared kind
  instead of `write` unconditionally, so a server declared `read` survives a role's `write`
  denial; a tool outside a non-empty `tools` list is recorded as skipped. Requirement 6 reworded;
  Status, Non-goals, Interface Contracts, Wire format and CLI syntax updated for `--kind`/`--tools`.
  A file from before this version loads unchanged.

### Version 1.4.0 (2026-09-21)

- Requirement 21 reworded (W36-C2): `--env`/`--timeout` rejection is scoped to flags given before `--`, and the rule holds through the real CLI entry point, where Click used to consume the separator and `docket mcp servers add` always failed.

### Version 1.3.1 (2026-09-18)

- Alignment pass: the browser recipe (Examples, step 2) no longer calls `load_mcp_tools` "not yet a
  live path" — `DocketDriver.run_turn` has called it since 1.2.0. Status's two pointers to
  sections that do not exist ("Measured per-turn cost", "Wired to the live turn path") now point
  at the Version 1.2.0 entry that holds that material. No requirement changed.

### Version 1.3.0 (2026-08-19)

- **Wave 20 context efficiency — MCP output ceiling parity.** Added Requirements 30-31 and wired
  `edges/adapters/mcp_client.py` to the live `docket.config.TOOL_MAX_OUTPUT_CHARS` value for every
  call. A configured small-context ceiling now bounds MCP results as well as built-ins, with the
  existing visible truncation marker; a regression test changes the value after module import and
  proves that two consecutive calls honor the two different limits.

### Version 1.2.0 (2026-08-05)

- **ROADMAP Phase 19/wave 17, card W17-1 — MCP tools reachable in a live turn.** Closed docket's
  oldest recorded known-true limit. Added Requirements 25-29 ("Live-turn wiring"):
  `edges/adapters/docket_runtime.py`'s `DocketDriver` gained an `mcp_loader` injection seam,
  called from `run_turn` right after `registry_factory()` and before `run_agent_turn`'s per-turn
  role narrowing — so a configured server's tools are folded into the registry the model sees and
  are subject to the same narrowing a built-in tool gets. Configuring a server
  (`docket mcp servers add`) now makes its tools usable on the very next turn.
  - **The blocking design question this card had to answer first:** a namespaced MCP tool name
    (`mcp__<server>__<tool>`) can never equal a literal `denied_tools` entry, so a naive wire would
    have silently given a Reviewer (or any write-denying role) every configured server's tools —
    falsifying this project's own "structural, not advisory" claim about role narrowing. Fixed in
    `role-archetypes.spec.md`'s new requirement 6, not here: `registry_for_role` now also excludes
    by `Tool.kind`, and every MCP-adapted tool is `kind="write"` unconditionally (unchanged from
    1.1.0's `_build_tool`) — so the existing kind data, not a new MCP-aware rule, closes the gap.
  - **Measured, not assumed, per-turn cost.** Zero configured servers (the default): one JSON read,
    averaging 0.0036ms over 1000 iterations, no subprocess. One configured server: a real subprocess
    round trip against `docket mcp serve` itself (a real, already-shipped MCP stdio server used as
    the measurement's "fake" server) averaged ~0.62s steady-state per server, per turn. **Decision:
    no caching in this version** — configuring a server is already the opt-in gate that determines
    who pays this cost, and a correct cache needs an invalidation signal tied to
    `MCP_SERVERS_FILE`'s content (Requirement 29) that does not exist yet; named trigger for a
    follow-up: more than one configured server, or measured turn latency dominated by MCP loading.
  - **What this version leaves honestly unwired:** no per-turn caching (above); HTTP/SSE transports
    still unsupported (unchanged scope); a read-only role gets zero MCP tools rather than a
    correctly narrowed nonzero set, because no per-tool trust/capability signal exists to
    distinguish a genuinely read-only remote tool from a write-capable one — the follow-up this
    leaves named, not started.

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
