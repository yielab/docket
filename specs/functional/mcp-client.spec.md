# MCP Client Specification

**Version**: 3.1.0
**Status**: Implemented and on the live turn path: configured servers' tools load into the turn's
registry before per-role narrowing, so a role that denies a capability loses them like a built-in.
Stdio transport only; each turn re-spawns every configured server (no listing cache). A server
declared `lifetime: hop` keeps one session open for the hop's calls (Requirements 41-46); every
other server is one subprocess per exchange. An `env` value may be `secret:<name>`, resolved from
docket's secret store when a turn loads its servers (Requirements 47-50).
**Last Updated**: 2026-10-30

## Purpose

Decision D-19 draws one line: docket owns the loop, the tool registry, tool dispatch and every
gate; it rents *protocols*. MCP is a tool transport, so it is rented, but docket stays the
dispatcher, which is why adopting it does not compromise the guardrails. This specification defines
the MCP *client* half: how docket connects to an externally configured MCP tool server, enumerates
the tools it offers, and adapts each one into an ordinary `Tool` registered, and therefore gated,
exactly like a built-in tool. docket also ships an MCP *server* (`docket start --mcp`, see
`mcp-server.spec.md`); this is the other direction.

## Scope

This specification covers:

- Docket-owned configuration of external MCP servers (`McpServerConfig`/`McpServerRegistry`,
  persisted through the docket-owned JSON store), global and pod-scoped
- Connecting to a configured server, enumerating its tools, and adapting each into a `Tool`
  registered into a `ToolRegistry` through its public `register` only
- The namespacing rule that makes a collision between an external tool and a built-in structurally
  impossible, and the narrower collision case it does not eliminate
- Failure isolation: how an unreachable, slow or misbehaving server degrades, and the bounded
  timeout that guarantees it
- Screening a remote tool's name/description, and its results, through the `pre_input` policy hook
  as untrusted input
- The `docket setup mcp list/add/remove` commands, which are presentation over the configuration
  functions
- The recipe this client exists to unlock: pointing docket at an off-the-shelf MCP server
  (browser automation, web search) as configuration rather than code (see Examples)
- `DocketDriver`'s `mcp_loader` seam: the call that makes a configured server's tools reachable by
  a running agent, and the ordering guarantee (loaded before role narrowing)
- The pod's `mcpServers` selection as it applies to loading
- The directory and jail a stdio server starts in during a turn
- The model-visible output ceiling for a remote tool result
- A server's `lifetime`: one stdio session that answers all of a hop's calls, and where it ends

This specification does NOT cover:

- The tool schema, the registry, or the `dispatch_tool` chokepoint. Every adapted tool is gated by
  the unmodified `dispatch_tool`/`evaluate_tool_call`; see `security-gates.spec.md` and the
  acceptance test `TestGatedExactlyLikeABuiltin`
- `docket start --mcp` (docket exposing its own control plane as MCP tools); see
  `mcp-server.spec.md`
- Non-stdio MCP transports (HTTP/SSE)
- A session that outlives its hop (`lifetime: task`): deferred until a recorded run needs it
- The browser (or any program) a server drives: it runs outside docket and is not started,
  stopped or governed by this client
- The role-narrowing mechanism itself (kind-based exclusion); `role-archetypes.spec.md` owns it.
  This specification only states that MCP tools are loaded before it runs, and why that ordering
  matters: a namespaced name can never equal a denied built-in name, so denial must be by
  capability (`Tool.kind`), never by name
- Caching a server's tool listing: none exists. Each turn that reaches a configured server
  re-spawns it (measured ~0.6s per stdio server per turn; zero servers spawn nothing)
- Per-tool trust metadata. `kind` and `tools` are declared once per server, so a server that mixes
  read and mutating tools is either trusted whole (`kind: read`) or not at all (default `write`)
- Proving a `kind: read` declaration true: it is an operator assertion recorded at configuration
  time; nothing connects to a server and inspects what its tools do

## Requirements

### Configuration

1. A configured MCP server **MUST** be docket-owned state, persisted through the docket-owned JSON
   store (`MCP_SERVERS_FILE`, default `docket-mcp-servers.json` under `DOCKET_HOME`) like every
   other docket-owned JSON file, never written directly.
2. A server's `name` **MUST** be unique among configured servers and **MUST** contain only
   letters, digits, `-`, or `_`; `add_mcp_server` **MUST** reject anything else with a descriptive
   error rather than silently normalizing it.
3. A server's per-call `timeout`, whether configured or defaulted, **MUST** be resolved through
   `McpServerConfig.resolved_timeout()`, which **MUST** clamp it to `MCP_CLIENT_MAX_TIMEOUT_S`
   (default 60) regardless of what was requested. A `timeout` of `0` means `MCP_CLIENT_TIMEOUT_S`
   (default 10).

### Enumeration and adaptation

4. `load_mcp_tools` **MUST** connect to every configured server (or the explicit `servers=`
   argument, for a caller that wants a subset), enumerate its tools, and register each as a `Tool`
   into the caller-supplied `ToolRegistry` using only that registry's public `register` method.
5. Every call an adapted tool's handler makes **MUST** ultimately reach `dispatch_tool`, the same,
   unmodified chokepoint a built-in tool call reaches. The MCP client **MUST NOT** invoke an adapted
   tool's handler itself under any circumstance; the only thing it does with a `Tool` object is
   build it and hand it to `ToolRegistry.register`.
6. An adapted tool's `kind` **MUST** be its server's declared `McpServerConfig.kind` (`"read"`,
   `"write"` or `"send"`, default `"write"`), never `"exec"`: an MCP tool call is not a shell command and does
   not carry the `args["command"]` shape `evaluate_tool_call`'s exec-kind path expects. This does
   not weaken gating: the `pre_tool_call` policy hook gates every tool kind identically
   (Requirement 5); only the additional shell-command classification is kind-specific, and an MCP
   call is correctly excluded from it.

### Namespacing (the collision rule)

7. Every adapted tool **MUST** be registered under `mcp__<server-name>__<remote-tool-name>`
   (`NAMESPACE_PREFIX`, followed by the server's *locally configured* name, never a name the remote
   server reports about itself).
8. No built-in tool name **MUST** ever start with `mcp__`, so that an adapted tool's name can never
   equal, and therefore never silently overwrite, a built-in registration, regardless of what an
   external server calls its own tools.
9. Two different configured servers exposing a tool with the same remote name **MUST** both be
   registered, under their own distinct namespaced names.
10. A namespaced name that is already present in the target registry for any other reason
    (including a previous `load_mcp_tools` call against the same registry object) **MUST** be
    skipped, not overwritten: loading only ever adds registrations, never replaces one.

### Failure isolation

11. A server that cannot be reached, times out, or returns a malformed tool listing **MUST NOT**
    raise out of `load_mcp_tools`. The failure **MUST** be recorded in that server's
    `McpServerLoadResult` and audited (`mcp_client.unavailable`), and processing **MUST** continue
    to the next configured server.
12. A failure isolated to one server **MUST NOT** remove or affect tools already registered from
    another server, or docket's own built-ins already present in the registry before
    `load_mcp_tools` was called.
13. Every connect/list/call exchange with a server **MUST** be wrapped in a hard wall-clock bound.
    An unresponsive server **MUST** be cancelled and reported as unavailable, never awaited
    indefinitely.

### Untrusted tool descriptions

14. Before registration, every remote tool's `"<name>: <description>"` text **MUST** be evaluated
    through `policy_eval_detail(role, "pre_input", text, trusted=False, project=<the calling pod>)`,
    the same evaluator (and the same shipped `prompt-injection` policy) that screens task text, the
    pod's own `on: input` policies included.
15. A `block` or `require_approval` result **MUST** prevent that tool from being registered at all,
    and **MUST** be audited (`mcp_client.tool_description_blocked`). `require_approval` is
    deliberately folded into the same refusal as `block`: there is no per-tool human-approval
    channel for a static piece of catalog text, and `load_mcp_tools` **MUST NOT** create a pending
    approval, block, or otherwise wait for one on a tool description.
16. A `warn` or `redact` result **MUST NOT** prevent registration, but **MUST** be audited
    (`mcp_client.tool_description_warn`).
17. An `allow` result, or no policy hit at all, **MUST** register the tool with no audit entry,
    matching `dispatch_tool`'s own convention that only a non-allow decision is worth a record.

### Optional dependency discipline

18. The official `mcp` Python SDK **MUST NOT** become a base dependency (extra: `docket[mcp]`). The
    transport adapter **MUST** import it lazily and **MUST NOT** let a missing SDK surface as a bare
    `ImportError` traceback: both `list_remote_tools` and `call_remote_tool` **MUST** return an
    ordinary failed result carrying an actionable install hint instead.
19. Neither `list_remote_tools` nor `call_remote_tool` **MUST** ever raise for an ordinary failure
    (missing SDK, spawn failure, protocol error, timeout, malformed response). Every one of those
    comes back as data (`McpListResult(ok=False, ...)` / `ToolOutcome(False, ...)`).

### CLI (`docket setup mcp`)

20. `docket setup mcp list` **MUST** show every configured server's name and launch command (plus
    kind, tools allow-list, timeout and env), **MUST NOT** print any `env` value in the clear (mask
    as `KEY=****`, in the table and in `--json`, matching `docket setup provider list`), and
    **MUST NOT** connect to any server: it is a pure read of the global server configuration.
21. `docket setup mcp add <name> [--env KEY=VALUE ...] [--secret VAR=NAME ...] [--timeout SECONDS] [--kind read|write|send]
    [--tools NAME,NAME,...] -- <command> [args...]` **MUST** treat everything after a literal `--`
    token as the server's launch command and arguments verbatim, so a command's own flags (e.g.
    `npx -y ...`, or a `--env`/`--timeout` that belongs to the launched process rather than to
    `docket`) are never misparsed as `docket`'s own flags. A malformed `--env` **MUST** be rejected
    with a descriptive error (exit 1); a non-numeric `--timeout` and a command flag with no
    separator before it are usage errors (exit 2) and **MUST NOT** silently swallow the rest of the
    arguments as flags. This holds across the real CLI entry point, where Typer declares the options
    and the trailing arguments; there is no hand-parsed argv recovery.
22. `docket setup mcp add` **MUST** build one `McpServerConfig` from the parsed name, command, args,
    env, timeout, kind and tools and pass it to `add_mcp_server` unchanged, surfacing that
    function's `ValueError` (bad or duplicate name) as a CLI error (exit 1) rather than a
    traceback. A `--kind` other than `read`, `write` or `send` **MUST** exit 1 naming the flag.
23. `docket setup mcp add`/`remove` **MUST** write an audit entry (`mcp_servers.add` /
    `mcp_servers.remove`) naming the server and, for `add`, its launch command and kind. They
    **MUST NOT** record any `env` value, matching Requirement 20's masking rule for `list`.
    `docket setup mcp list` is read-only and **MUST NOT** write an audit entry.
24. None of `docket setup mcp add/list/remove` **MUST** import any tool registration, tool handler or
    the tool dispatcher; the commands only call the configuration functions in Requirements 1-3.
    Connecting to a server and adapting its tools remains `load_mcp_tools`'s job, called by
    `DocketDriver.run_turn` (Requirement 25).

### Live-turn wiring

25. `DocketDriver` **MUST** expose an `mcp_loader` seam, a callable invoked as
    `mcp_loader(registry, role, project, launch=<StdioLaunch>)` that returns the
    `McpServerLoadResult` list. It defaults to a wrapper around `load_mcp_tools` that applies the
    pod's server selection (Requirement 34), so a test can substitute a fake `list_tools`/`call_tool`
    pair (Requirement 4's port) without spawning a subprocess or requiring the `mcp` SDK.
26. `DocketDriver.run_turn` **MUST** call `mcp_loader(registry, meta.role, ctx.project, launch=...)`
    against the registry returned by `registry_factory()` (typically `builtin_registry()`)
    **before** that registry is handed to `run_agent_turn`, i.e. before `registry_for_role`'s
    once-per-turn narrowing runs (`agent-loop.spec.md`). This ordering **MUST NOT** be reversed:
    narrowing after loading is what lets `role-archetypes.spec.md` requirement 6 (kind-based
    exclusion) see, and exclude, an MCP-adapted tool for a role that denies the capability it
    represents.
27. A zero-server install (no server configured, or the pod's selection leaves none) **MUST**
    produce a registry, a system prompt and a set of tool advertisements to the model identical to
    a driver with no MCP loading. `load_mcp_tools` with zero servers **MUST NOT** mutate the
    registry, write an audit entry, or spawn a subprocess. (The default loader is still called; it
    registers nothing.)
28. Nothing in `DocketDriver.run_turn`'s use of `mcp_loader` **MUST** change `run_agent_turn`'s
    "never raises for an ordinary failure" contract (`agent-loop.spec.md`). `load_mcp_tools` never
    raises (Requirements 11-13, 19), so a server that is unreachable, hung (bounded by
    Requirement 13) or returns a malformed listing degrades to "unavailable" and the turn proceeds
    on whatever registry resulted, never failing solely because of MCP loading. The one deliberate
    exception is Requirement 34's pod-scoped selection: a caller misconfiguration, not a
    live-server failure, so it raises instead of degrading.
29. A listing and each tool call **MUST** each spawn a fresh stdio subprocess for exactly one
    exchange and tear it down again, per call unless the server declares `lifetime: hop`
    (Requirements 41-46). No tool listing is kept between turns, and no connection is kept between
    calls of a `call` server, so a misbehaving server cannot corrupt a later, unrelated call's
    state. A `hop` session never outlives the hop that opened it.

### Server lifetime (`call` | `hop`)

41. `McpServerConfig` **MUST** carry `lifetime: Literal["call", "hop"] = "call"`. A config written
    before the field existed, or without it, loads as `call` and behaves byte for byte as before. A
    `kind: mcp-server` document **MUST** accept `lifetime: call|hop` too (default `call`) and
    `mcp_server_document` **MUST** write it back when it is `hop`.
    `docket setup mcp add` **MUST** accept `--lifetime call|hop` (any other value exits 1 naming the
    flag), and `list --json` shows the field. A tool listing is always one subprocess per exchange,
    whatever the lifetime.
42. For a `hop` server the first tool call of a hop **MUST** open one stdio session, and every
    later call of that hop to that server **MUST** be answered over the same session (the server's
    own state, such as a page it navigated, is therefore still there). The next hop **MUST** open a
    fresh session. A `call` server **MUST NOT** be affected: each call spawns its own subprocess.
43. A session **MUST** be closed where the hop ends (`DocketDriver.run_turn`'s `finally`, beside the
    stop of the hop's background processes), on every exit path. Opening a session **MUST** be
    reported to `ToolContext.on_process` as `started` and closing it as `exited`, each carrying
    `tool: "mcp"` and `server: <name>`; the close at hop end adds `reason: "turn_end"`. Each
    session therefore yields exactly one `process_started` and one `process_exited` trace event, and
    a hop that called no `hop` server yields none.
44. A `hop` session **MUST** apply, per call and unchanged, what a `call` exchange applies: the same
    launch (`StdioLaunch`: directory and jail argv, Requirement 40), the same per-call wall-clock
    bound (Requirement 13; a call that times out ends its session), the same output bound
    (Requirement 30) and the same `pre_input` screening of the result (Requirement 35); and the call
    **MUST** still reach the transport only through `dispatch_tool` (Requirement 5). Opening a
    session is bounded by the same timeout; a server that cannot start reports the same failed
    outcome a `call` server does.
45. A `hop` server that has died (killed, crashed, or no longer answering a liveness probe) **MUST**
    be restarted by the next call, and that call's output **MUST** begin with a line saying the
    server was restarted and its state from earlier calls in the hop is gone. A server that dies
    during a call fails that call with an error saying so and the state is gone; it is not
    retried, because the call may have had an effect. The dead session's `exited` is reported once,
    at the moment it is found dead (with `reason: "died"`, or `"timeout"` after a timed-out call).
46. The session is a runtime object owned by the hop's `ToolContext` (`mcp_sessions`); it **MUST
    NOT** be stored in `McpServerConfig`, any document or the trace. Because the hop's calls are
    sequential, a session serves one call at a time.

### Credentials from the secret store

47. An `env` value of the form `secret:<name>` (`<name>` is `[A-Za-z0-9_.-]+`) **MUST** be a
    reference to a stored secret. It is stored exactly as written: `mcp-servers.json`, a pod-scoped
    file and a `kind: mcp-server` document (`McpServerDocument.env`, `mcp_server_document`) carry the
    reference and **MUST NOT** ever carry the value, and a document or config round-trips unchanged.
    A value that is not a reference is a literal and loads as before.
48. `docket setup mcp add` **MUST** accept `--secret VAR=<name>` (repeatable), which writes the
    entry `VAR: secret:<name>` into the server's `env`. It never reads or prints the secret's value;
    a malformed pair, or a `VAR` also given to `--env`, exits 1 naming the flag. A `<name>` with no
    stored secret is allowed (the secret may be stored later) and **MUST** be reported as a warning
    naming the variable and the secret's name.
49. The live turn **MUST** resolve every reference where it loads its servers (after Requirement
    34's selection, before `load_mcp_tools`) through `governance.secrets.secret_value`, into a copy
    of the config handed to the load; the stored config is not changed. A server one of whose
    references names no stored (or an empty) secret **MUST NOT** be loaded for that turn: it is
    recorded as an `mcp_client.unavailable` audit event and an `McpServerLoadResult` with
    `ok=False` whose error names the variable and the secret's name, never a value; the pod's other
    servers **MUST** still load and the turn **MUST NOT** fail on this alone (Requirement 28). A
    value resolved from the store reaches only the server's process environment; because it is a
    stored secret it is removed from the trace, the audit log and exports like any other.
50. `docket setup --fix` (the health check, `run_check`) **MUST** warn once per server and variable when a server's `env` holds
    a literal value under a credential-shaped name (one ending `_TOKEN`, `_KEY`, `_SECRET` or
    `_PASSWORD`), naming the server and the variable and the `--secret` fix, and **MUST NOT** print
    the value. The warning is advisory: it is not counted as a critical issue.

### Model-visible output bound

30. `call_remote_tool` **MUST** visibly truncate rendered remote output at
    `DOCKET_TOOL_MAX_OUTPUT_CHARS`, the same operator-controlled context ceiling used by built-in
    tools. The marker **MUST** report how many characters were omitted.
31. The adapter **MUST** resolve that ceiling on every call, not copy it into a constant or default
    argument at import time. Changing the configured value after import **MUST** affect the next
    remote tool result.

### Declared kind and tool subset

32. `McpServerConfig` **MUST** carry `kind: Literal["read", "write", "send"] = "write"` and
    `tools: list[str] = []`. Both are operator assertions validated at write time (a `kind` outside
    `{"read", "write", "send"}` **MUST** be rejected: the model's validation error is a `ValueError`, and the
    CLI refuses it first with an exit-1 error naming the flag, per Requirement 22); neither is ever inferred by connecting to the
    server. An empty `tools` list means "every tool the server advertises"; a non-empty one is the
    exhaustive allow-list of remote tool names `load_mcp_tools` **MUST** register. Every other
    advertised tool **MUST** be recorded in that server's `McpServerLoadResult.skipped` with an
    `McpToolSkip` reason naming that it is "not in the server's `tools` list", exactly like
    Requirement 10's collision-skip, never silently dropped. A stored server without `kind` or
    `tools` **MUST** load as `kind="write", tools=[]`. `send` declares that a tool acts outside the
    machine: it sends a message, submits a form, posts, books, pays, or asks another agent to. The
    tools of a `send` server register with `ToolKind` `send`; a server that both reads and acts is
    declared twice, once `read` and once `send`. A `send` tool **MUST NOT** reach any role by
    default: `registry_for_role` offers it only to a role whose own `tools` allow-list names it
    (`role-archetypes.spec.md`, "Tools and calls per hop" requirement 5). `write`'s semantics are
    unchanged: `cannot: [write]` removes a `write` tool and leaves a `send` tool alone.
33. The load outcome `load_mcp_tools` returns for each server **MUST** name that server's declared
    `kind`, so an operator or an audit-trail reader can see which trust level a given load ran under
    without re-reading the config file.

### Pod-scoped server selection

34. The live turn **MUST** filter the server catalog (global servers plus the turn's pod-scoped ones,
    Requirements 37-38) by the pod's `mcpServers` setting (`pod-dispatch.spec.md`'s "Pod dispatch
    settings" item 7) before calling `load_mcp_tools`. An unset setting, or a turn with no pod,
    **MUST** load every configured server. A selection naming a server absent from the *live*
    catalog **MUST** raise `DispatchError` naming it, instead of silently loading the remaining
    servers or none at all: a stale selection (the server was renamed or removed after
    `docket pod set`) **MUST** be loud. This re-check runs on every read, through
    `PodSettings.coerce` rather than `PodSettings.load_for`, so an unrelated malformed pod setting
    never blocks MCP loading (see `pod-dispatch.spec.md` item 7), not only at `docket pod set` time.

### Untrusted tool results

35. The text of a remote tool's result **MUST** be evaluated, inside the adapted tool's handler,
    through the `pre_input` hook with `trusted=False` (`role=ctx.role`, `project=ctx.project`), the
    pod's own `on: input` policies included; *text* is the outcome's `content` when it succeeded and
    its `error` when it did not. A result with no text **MUST** pass unchanged and unaudited.
36. A `block` or `require_approval` result **MUST** replace the outcome with `ok=False` whose error
    names the server and the policy id (never the result text), and **MUST** be audited
    (`mcp_client.tool_result_blocked`, naming server, tool, policy and action). A `redact` result
    **MUST** return the text passed through the trace redactor, and a `warn` result **MUST** return
    it unchanged; both **MUST** be audited (`mcp_client.tool_result_warn`). `allow`, or no hit,
    passes the outcome byte-identical with no audit entry. Built-in tool results are screened by
    their own requirements (`security-gates.spec.md`).

### Pod-scoped servers (recipe-declared)

37. A server declared by a recipe **MUST** be stored under its pod, in the pod's
    `config/mcp-servers.json` (the `McpServerRegistry` shape), written through the docket-owned JSON
    store. `load_mcp_servers(project)` **MUST** return the global servers followed by that pod's own;
    `load_mcp_servers()` with no project **MUST** stay global-only. A pod-scoped name equal to a
    global name **MUST** be refused at apply, never shadowed. The live turn **MUST** load a pod's own
    servers for that pod only.
38. The `mcpServers` pod setting **MUST** accept a global name or a name in this pod's own pod-scoped
    file, and **MUST** refuse any other name; a name that belongs to another pod **MUST** be refused
    with an error saying so. Nothing installs a pod-scoped server except `docket pod update`
    (ADR 0012): `docket pod validate`, `docket pod update --dry-run`, `docket init --no-apply` and
    dispatch write nothing.

### Turn root for stdio servers

39. A stdio server spawned for a live turn **MUST** start in that turn's resolved root: the same
    `ctx.roots[0]` the built-in file tools are confined to (the task worktree, else the codebase,
    else the member's work directory, else the workspace). `DocketDriver.run_turn` **MUST** pass it
    to `mcp_loader` inside the one `launch` keyword (a frozen `StdioLaunch`: `cwd`, `sandbox`,
    `network`, `roots`, `read_only`); `load_mcp_tools(..., launch=)` **MUST** carry it to every
    listing and adapted call. It is a runtime argument and **MUST NOT** be stored in
    `McpServerConfig` or any document. A caller outside a turn passes no `launch`, and the server
    then inherits the process's directory and runs unjailed.
40. When the turn is isolated (`launch.sandbox == "auto"`) a stdio server **MUST** start inside the
    turn's jail: the server's `command`+`args` are wrapped with the resolved backend (Landlock,
    Seatbelt or Docker) over the turn's roots, read-only mounts and the network mode `bash` gets,
    keeping the stdio pipes (Landlock and Seatbelt pass them through; Docker runs with `-i`). With
    no usable backend, or no root to jail to, the server **MUST NOT** start; it is reported
    unavailable (Requirement 11) and, for a call, as a failed outcome. There is no per-server
    opt-out: `McpServerConfig` and the `kind: mcp-server` document have no `isolate` field,
    `docket setup mcp add` has no `--no-isolate`, and an `isolate:` key in a document is an ordinary
    unknown-key error. With isolation off, or no `launch`, the argv **MUST** be the server's own,
    unchanged. Under Docker (`docket setup sandbox backend docker`) the server binary must exist in
    the image.

## Interface Contracts

### Configuration and adaptation API

```python
NAMESPACE_PREFIX = "mcp__"

class McpServerConfig(BaseModel):              # name, command, args, env, timeout, kind, tools, lifetime
    def resolved_timeout(self) -> float: ...   # clamped to MCP_CLIENT_MAX_TIMEOUT_S
    # kind: Literal["read", "write", "send"] = "write" -- declared trust level, an operator
    #   assertion (Requirement 32), never inferred by connecting to the server
    # tools: list[str] = []                    -- non-empty = exhaustive allow-list of
    #   remote tool names to register; empty = register everything advertised
    # lifetime: Literal["call", "hop"] = "call" -- "call": one subprocess per exchange (today);
    #   "hop": one stdio session answers the hop's calls (Requirements 41-46)

    # env values: a literal, or `secret:<name>` resolved at turn load (Requirements 47-49)

class McpServerRegistry(BaseModel):            # servers: list[McpServerConfig]

def load_mcp_servers(project: str = "") -> list[McpServerConfig]: ...  # global, then project's own
def add_mcp_server(config: McpServerConfig) -> None: ...      # raises ValueError on bad/dup name
def remove_mcp_server(name: str) -> bool: ...                  # False if not found
def namespaced_tool_name(server_name: str, remote_tool_name: str) -> str: ...

# pod-scoped servers (Requirements 37-38)
def pod_mcp_servers_file(project: str) -> Path: ...
def load_pod_mcp_servers(project: str) -> list[McpServerConfig]: ...
def write_pod_mcp_servers(project: str, servers: list[McpServerConfig]) -> None: ...
def pod_scoped_owner(name: str, *, exclude: str = "") -> str: ...  # pod declaring it, else ""

# the kind: mcp-server document (same fields; `access` carries read|write|send because `kind:` is the
# envelope; `lifetime` is `call|hop`, Requirement 41)
class McpServerDocument(BaseModel): ...
class McpServerDocError(ValueError): ...
def load_mcp_server_document(path: str | Path) -> McpServerConfig: ...

class McpRemoteTool:                            # name, description, parameters (frozen dataclass)
class McpListResult:                            # ok, tools, error

@dataclass(frozen=True)
class StdioLaunch:                              # cwd, sandbox ("auto"|"off"), network, roots, read_only

class ListToolsFn(Protocol):                    # (config, timeout, launch=None) -> McpListResult
class CallToolFn(Protocol):                     # (config, name, arguments, timeout, launch=None) -> ToolOutcome

class McpToolSkip:                              # tool_name, reason
class McpServerLoadResult:                      # server, ok, kind, registered, skipped, error

def load_mcp_tools(
    registry: ToolRegistry,
    *,
    servers: Sequence[McpServerConfig] | None = None,   # default: load_mcp_servers()
    list_tools: ListToolsFn | None = None,               # default: the transport adapter
    call_tool: CallToolFn | None = None,                 # default: the transport adapter
    role: str = "",                                       # feeds the pre_input policy check
    project: str = "",                                    # the calling pod, for its on: input policies
    launch: StdioLaunch | None = None,                    # how stdio servers start (Requirements 39-40)
) -> list[McpServerLoadResult]: ...
```

### Transport adapter API

```python
MISSING_SDK_HINT: str

def list_remote_tools(config: McpServerConfig, timeout: float, launch: StdioLaunch | None = None) -> McpListResult: ...
def call_remote_tool(
    config: McpServerConfig, name: str, arguments: dict[str, Any], timeout: float,
    launch: StdioLaunch | None = None,
) -> ToolOutcome: ...

class HopSessions:                              # the hop's open `lifetime: hop` sessions (ToolContext.mcp_sessions)
    def call(self, config, name, arguments, timeout, launch=None, on_process=None) -> ToolOutcome: ...  # opens or restarts
    def close_all(self, on_process, *, reason: str) -> None: ...   # one `exited` per open session
```

The adapted tool of a `hop` server calls `ctx.mcp_sessions.call(...)` where a `call` server's calls
`call_remote_tool(...)`; both return a `ToolOutcome`, and the result screen (Requirement 35) is
the same. `DocketDriver.run_turn` calls `ctx.mcp_sessions.close_all(ctx.on_process, reason="turn_end")`
right after `background.stop_all`. P55-3 and later work on `kernel/mcp.py` and `mcp_tools.py` should
keep this seam: the session is looked up from the context at call time, never captured at load time.

### `DocketDriver`'s wiring seam

```python
@dataclass
class DocketDriver:
    backend_factory: Callable[[str], ChatBackend | None] = client_for
    registry_factory: Callable[[], ToolRegistry] = builtin_registry
    mcp_loader: Callable[..., list[Any]]   # (registry, role, project, *, launch=None); default applies Requirement 34

    def run_turn(self, agent_id: str, session_key: str, message: str, ...) -> TurnResult:
        ...
        registry = self.registry_factory()
        self.mcp_loader(registry, meta.role, ctx.project, launch=launch)   # folds MCP tools in, before role narrowing
        ...
        result = run_agent_turn(backend, registry, ctx, session_key, message, config=loop_config)
```

`mcp_loader` is a fixed, narrow wrapper around `load_mcp_tools`'s keyword-heavy signature so a test
can substitute a fake without matching that full surface (Requirement 25). `project` is what
Requirement 34's `mcpServers` filtering keys off.

### Wire format (`$MCP_SERVERS_FILE`)

```json
{
  "servers": [
    {
      "name": "weather",
      "command": "npx",
      "args": ["-y", "@example/weather-mcp-server"],
      "env": {"API_TOKEN": "secret:weather"},
      "timeout": 0.0,
      "kind": "write",
      "tools": [],
      "lifetime": "call"
    }
  ]
}
```

`timeout: 0.0` means "use `MCP_CLIENT_TIMEOUT_S`"; any other value is still clamped to
`MCP_CLIENT_MAX_TIMEOUT_S`. `kind`, `tools` and `lifetime` are optional on read (Requirements 32, 41) and default to
`"write"`, `[]` and `"call"`.

### CLI syntax

```
docket setup mcp list [--json]
docket setup mcp add <name> [--env KEY=VALUE ...] [--timeout SECONDS]
    [--kind read|write|send] [--tools NAME,NAME,...] [--lifetime call|hop] -- <command> [args...]
docket setup mcp remove <name>
```

`--kind`/`--tools`/`--lifetime`/`--secret` follow the same before-`--` convention as `--env`/`--timeout` (Requirement 21).
`--tools` takes a single comma-separated argument (no repeated flag, unlike `--env`) since it names
a subset of one server's own tools, not a set of independent key/value pairs.

`add`'s `--`-separator convention is deliberate: an MCP server's own launch command frequently
carries flags of its own (`npx -y ...`, `-- --headless`, ...), and a flag-parser that tried to
distinguish docket's flags from the command's by position alone would misparse the first one it
saw. Everything after `--` is opaque to docket.

## Examples

### Recipe: browser support (and web search) is configuration, not code

Pointing docket's MCP client at an existing MCP server for a capability is a configuration step, and
the client gates whatever that server advertises exactly like a built-in tool, with no special-casing
for "this tool drives a browser".

1. **Configure the server.** The [Playwright MCP server](https://github.com/microsoft/playwright-mcp)
   is a stdio MCP server that drives a real browser and ships as an `npx` package, so nothing beyond
   Node is required. The browser itself runs outside docket (started and stopped by the operator);
   the server only attaches to it over `--cdp-endpoint`. The server keeps the page and its element
   refs between calls, so it declares `--lifetime hop`: one session answers the hop's calls
   (Requirement 42), where a `call` server would lose the page after the first call.

   ```
   docket setup mcp add playwright --lifetime hop -- npx -y @playwright/mcp@latest --cdp-endpoint http://127.0.0.1:9222
   ```

2. **What this buys, mechanically.** On the next turn every tool Playwright advertises
   (`browser_navigate`, `browser_click`, `browser_snapshot`, ...) registers as
   `mcp__playwright__<tool>` (Requirement 7). Even a hostile fork naming one of its own tools `bash`
   cannot make `mcp__playwright__bash` collide with or shadow the real, gated `bash` tool
   (Requirement 8; see "A malicious server cannot shadow a built-in" below and
   `TestCollisionRule.test_a_malicious_server_naming_itself_after_a_builtin_tool_does_not_shadow_it`).
   Every call still passes through the unmodified `dispatch_tool` chokepoint: the same
   `pre_tool_call` policy hooks, approval routing and audit trail a `bash` or `edit` call gets
   (Requirement 5).
3. **The same for web search**: configure any MCP-compliant search server
   (`docket setup mcp add search -- <its stdio launch command>`) and its tools register as
   `mcp__search__<tool>`, gated the same way. Nothing in the client is browser- or search-specific;
   the mechanism is the transport, not the capability.
4. **Remove it just as cheaply**: `docket setup mcp remove playwright`. No code to revert.

docket ships no browser driver or search client; the entire "browser support" is the one `add`
command above, plus whatever server-side package the operator chooses to trust.

### Registering a server's tools alongside the built-ins

```python
registry = builtin_registry()
config = McpServerConfig(name="weather", command="npx", args=["-y", "@example/weather-mcp-server"])
reports = load_mcp_tools(registry, servers=[config], role="implementer")

# registry now also contains "mcp__weather__get_forecast" (or whatever the
# server advertises), gated by the same dispatch_tool as "read"/"write"/"bash".
```

### A malicious server cannot shadow a built-in

```python
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
  `ListToolsFn`/`CallToolFn` shapes exactly. Production code omits both and gets the real transport
  adapter lazily.

### Post-conditions

- After `load_mcp_tools`, every name in `McpServerLoadResult.registered` **MUST** be present in the
  target registry and **MUST** start with `mcp__`.
- After `load_mcp_tools`, every built-in tool name present in the registry beforehand **MUST** still
  resolve to its original `Tool` object (identity-preserving, not merely name-preserving).
- A tool skipped for a policy reason (`McpToolSkip.reason` naming a policy) **MUST NOT** appear in
  the registry under its namespaced name.
- `docket setup mcp add`'s parsed `command`/`args` **MUST** match exactly what followed `--` on the
  command line, in order; the CLI **MUST NOT** reorder, deduplicate, or otherwise transform the
  launch command it was given.
- `docket setup mcp list` **MUST NOT** ever cause a subprocess to be spawned.
- With zero configured servers, `DocketDriver.run_turn`'s registry and the tool specs advertised to
  the model **MUST** be exactly the built-ins, pinned by `TestZeroServersIsUnchanged`.
- A role whose `denied_tools` implies kind `write` (every archetype that denies `write`/`edit`)
  **MUST NOT** be advertised, and **MUST NOT** be able to dispatch, any MCP-adapted tool from a
  server left at `kind: write`, proven end to end through `DocketDriver.run_turn` (not only at
  `registry_for_role`'s own level) by `TestReviewerNeverGainsAWriteCapableMcpTool`.

### Invariants

- No adapted tool name **MUST** ever equal a built-in tool name, for any server name or remote tool
  name whatsoever (the `mcp__` prefix is unconditional).
- `list_remote_tools`/`call_remote_tool` **MUST NOT** ever propagate an exception to their caller.
- A call to an adapted tool **MUST NOT** be able to reach its underlying protocol exchange without
  first passing through `dispatch_tool`'s gate. The MCP client holds no reference to a handler it
  did not just build for `ToolRegistry.register`, and calls the handler nowhere itself.
- The MCP client and the `docket setup mcp` commands **MUST NOT** import any built-in tool handler
  from the toolbox beyond the inert `ToolOutcome` result type (`TestOnlyTheInertResultTypeIsImported`);
  the CLI is configuration only, never a second execution path.
- A failure isolated to `DocketDriver.mcp_loader` (an unreachable, hung or malformed-listing server)
  **MUST NOT** cause `run_turn` to return `ok=False` on its own; only an otherwise-real turn failure
  (backend error, timeout, budget) may do that (Requirement 28).
- A pod's stale `mcpServers` selection (Requirement 34) is not this kind of failure: it **MUST**
  raise `DispatchError` out of `run_turn` rather than folding into a `TurnResult(ok=False, ...)`.
  A caller misconfiguration surfaces to its caller's own settle/fail path (`pod-dispatch.spec.md`),
  never as an ordinary turn outcome.

## Implementation

- `src/docket/agent/tools/mcp_tools.py`: `McpServerConfig`, `McpServerRegistry`, `McpServerDocument`,
  `McpServerDocError`, `StdioLaunch`, `McpRemoteTool`, `McpListResult`, `McpToolSkip`,
  `McpServerLoadResult`, `ListToolsFn`, `CallToolFn`, `NAMESPACE_PREFIX`, `load_mcp_servers`,
  `add_mcp_server`, `remove_mcp_server`, `namespaced_tool_name`, `load_mcp_tools`,
  `load_mcp_server_document`, `pod_mcp_servers_file`, `load_pod_mcp_servers`,
  `write_pod_mcp_servers`, `pod_scoped_owner`
- `src/docket/agent/tools/mcp_client.py`: `list_remote_tools`, `call_remote_tool`, `HopSessions`,
  `MISSING_SDK_HINT`; the output truncation, the jail wrapping of a stdio server's argv, and the
  hard wall-clock bound (`anyio.fail_after`)
- `src/docket/hops/application/driver.py`: `DocketDriver.mcp_loader` and its default wrapper
  (the pod `mcpServers` selection, the `StdioLaunch` built from the turn's context);
  `driver_support.py` resolves `secret:` references before the load (Requirement 49)
- `src/docket/interfaces/cli/commands/setup_check_services.py`: `check_mcp_literals` (Requirement 50)
- `src/docket/kernel/mcp.py`: `secret_reference`, `is_credential_name`; `src/docket/teams/mcp_servers.py`:
  `resolve_secret_env`, `McpSecretError`, `literal_credential_env` (Requirements 47-50)
- `src/docket/agent/tools/screening.py`: `screen_tool_result` (the untrusted-result screen used for MCP
  results); `src/docket/agent/tools/registry.py`: `dispatch_tool`, `ToolRegistry`
- `src/docket/teams/pod.py`: `PodSettings` `mcpServers` validation (Requirement 38)
- `src/docket/teams/apply/plan.py`: recipe `mcp-servers/` planning and the pod-scoped file write
- `src/docket/interfaces/cli/commands/setup_mcp.py`: `docket setup mcp list/add/remove`
- `src/docket/kernel/home.py`: the `Home` members `mcp_servers_file`, `mcp_client_timeout_s`,
  `mcp_client_max_timeout_s`, `tool_max_output_chars`, `pod_config_dir`
- Tests: `tests/integration/agent/test_mcp_client.py` (`TestCollisionRule`, `TestGatedExactlyLikeABuiltin`,
  `TestOnlyTheInertResultTypeIsImported`), `tests/unit/agent/tools/test_mcp_tools.py`
  (`TestZeroServersIsUnchanged`, `TestReviewerNeverGainsAWriteCapableMcpTool`),
  `tests/integration/interfaces/test_mcp_servers_cli.py`, `tests/integration/teams/test_recipe_mcp_servers.py`,
  `tests/integration/agent/tools/test_mcp_lifetime.py` (`lifetime: hop`, Requirements 41-46),
  `tests/integration/agent/tools/test_mcp_secret_env.py` (Requirements 47-49)
