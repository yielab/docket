#!/usr/bin/env python3
"""gen_cli_docs.py -- render docs/commands.md from the live Typer registry.

The registry is the source of truth: groups, commands, arguments, options
and each command's help text come from introspecting the same app object
`scripts/metrics.py::count_commands` counts, so no command's syntax is
typed a second time and `--check` fails when the committed file drifts.
Grouping, the global-options block and the reference tables belong to no
single command, so this script owns them directly.
Usage:
  ./scripts/gen_cli_docs.py            # regenerate docs/commands.md
  ./scripts/gen_cli_docs.py --check    # exit 1 if the file on disk is stale
"""

from __future__ import annotations

import ast
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
COMMANDS_MD = ROOT / "docs" / "commands.md"
MAIN_MODULE = SRC / "docket" / "__main__.py"

sys.path.insert(0, str(SRC))

# --- registry introspection -----------------------------------------------------


def _load_click_group():
    import typer.main

    from docket.cli import app

    return typer.main.get_command(app)


def _load_aliases_and_removed() -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    """Read the `_ALIASES`/`_REMOVED` literals as a syntax tree, because importing
    `__main__.py` would run the CLI: it calls `main()` at module scope."""
    tree = ast.parse(MAIN_MODULE.read_text(encoding="utf-8"), filename=str(MAIN_MODULE))
    aliases: dict[str, str] = {}
    removed: dict[str, tuple[str, ...]] = {}

    def _str(node: ast.expr) -> str:
        assert isinstance(node, ast.Constant) and isinstance(node.value, str)
        return node.value

    # Walk top-level statements in source order (not `ast.walk`'s traversal
    # order): `_REMOVED["wf"] = _REMOVED["workflow"]` below the main `_REMOVED
    # = {...}` literal depends on the literal having been processed first.
    for node in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            # `_REMOVED: dict[str, tuple[str, ...]] = {...}` is an AnnAssign,
            # not a plain Assign.
            target, value = node.target, node.value

        if target is None or value is None:
            continue

        if isinstance(target, ast.Name) and target.id == "_ALIASES":
            assert isinstance(value, ast.Dict)
            for k, v in zip(value.keys, value.values, strict=True):
                aliases[_str(k)] = _str(v)
        elif isinstance(target, ast.Name) and target.id == "_REMOVED":
            assert isinstance(value, ast.Dict)
            for k, v in zip(value.keys, value.values, strict=True):
                assert isinstance(v, ast.Tuple)
                removed[_str(k)] = tuple(_str(elt) for elt in v.elts)
        elif (
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name)
            and target.value.id == "_REMOVED"
            and isinstance(value, ast.Subscript)
            and isinstance(value.value, ast.Name)
            and value.value.id == "_REMOVED"
        ):
            # `_REMOVED["wf"] = _REMOVED["workflow"]` — an already-removed
            # name aliasing onto another removed name's message tuple.
            new_key = _str(target.slice)
            src_key = _str(value.slice)
            removed[new_key] = removed[src_key]

    return aliases, removed


# --- grouping (structural, script-owned) -----------------------------------------

# (heading, [command names in display order]) — every visible command must
# appear in exactly one group; `help` is folded into Global Options instead
# of its own heading, matching the previous hand-written structure.
GROUPS: list[tuple[str, list[str]]] = [
    ("Lifecycle Commands", ["list", "init", "add", "status", "info", "delete", "maintain"]),
    ("Session & Context Management", ["scope", "context", "persona"]),
    ("Pod Coordination", ["pod", "pipeline", "roles"]),
    ("Telegram Integration", ["wire", "unwire", "conversations"]),
    ("Keys & Authentication", ["keys", "auth"]),
    (
        "Utility Commands",
        [
            "logs",
            "edit",
            "profile",
            "models",
            "cost",
            "doctor",
            "config",
            "serve",
            "completions",
            "snapshot",
            "mcp",
        ],
    ),
    ("Security & Audit", ["gates", "audit", "policies", "approve", "deny"]),
    ("Observability Commands", ["runs", "trace", "metrics", "harness"]),
]

_TOC_SLUG_OVERRIDES = {
    "Command Aliases": "command-aliases",
}


def _slug(heading: str) -> str:
    """Slugify a heading the way Python-Markdown's `toc` extension does, so the
    anchors this script writes match the ones mkdocs renders."""
    import re as _re

    if heading in _TOC_SLUG_OVERRIDES:
        return _TOC_SLUG_OVERRIDES[heading]
    stripped = _re.sub(r"[^\w\s-]", "", heading.lower())
    return _re.sub(r"\s+", "-", stripped.strip())


# --- rendering --------------------------------------------------------------------


def _usage_line(name: str, cmd) -> str:
    import click

    parts = [f"docket {name}"]
    for param in cmd.params:
        if isinstance(param, click.Argument):
            token = param.name.replace("_", "-") if param.name else ""
            parts.append(f"[{token}]" if not param.required else f"<{token}>")
        elif isinstance(param, click.Option):
            flag = param.opts[-1] if param.opts else f"--{param.name}"
            parts.append(flag if param.is_flag else f"{flag} <value>")
    return " ".join(parts)


def _param_lines(cmd) -> list[str]:
    import click

    lines: list[str] = []
    for param in cmd.params:
        if param.name == "help":
            continue
        if isinstance(param, click.Argument):
            token = f"<{param.name}>" if param.required else f"[{param.name}]"
            lines.append(f"- `{token}`")
        elif isinstance(param, click.Option):
            flags = "`, `".join(param.opts)
            help_text = f" — {param.help}" if param.help else ""
            default = (
                ""
                if param.is_flag or param.default in (None, False, "")
                else (f" (default: `{param.default}`)")
            )
            lines.append(f"- `{flags}`{help_text}{default}")
    return lines


def _render_help_body(help_text: str) -> str:
    """Dedent a docstring for markdown embedding, preserving blank lines and
    escaping square brackets: optional-flag notation in plain prose reads as an
    empty reference link, which mkdocs-autorefs fails under `--strict`."""
    text = textwrap.dedent(help_text).strip()
    return text.replace("[", "\\[").replace("]", "\\]")


def _render_command(name: str, cmd, aliases_by_target: dict[str, list[str]]) -> str:
    out = [f"### {name}\n"]
    out.append(f"**Usage:** `{_usage_line(name, cmd)}`\n")
    params = _param_lines(cmd)
    if params:
        out.append("**Arguments & options:**\n")
        out.extend(p + "\n" for p in params)
        out.append("\n")
    help_text = cmd.help or cmd.get_short_help_str(limit=10_000) or ""
    out.append(_render_help_body(help_text) + "\n")
    alias_names = aliases_by_target.get(name, [])
    alias_str = ", ".join(f"`{a}`" for a in alias_names) if alias_names else "None"
    out.append(f"\n**Aliases:** {alias_str}\n")
    return "\n".join(out)


_GLOBAL_OPTIONS = """\
### --debug

Deprecated, hidden no-op: still accepted so existing scripts do not exit 2, sets nothing,
emits nothing; use the command's normal error output, `docket doctor`, traces and audit
records instead.

### --help / -h

Show Typer's auto-generated help for `docket` or any subcommand.

**Syntax:**
```bash
docket --help
docket -h
docket <command> --help
```

### help

{help_body}

**Syntax:**
```bash
docket help
```

**Aliases:** None

### --version / -V

Show the installed docket version.

**Syntax:**
```bash
docket --version
docket -V
```
"""

# NOTE ON THIS TABLE: like the old _ENV_VARS blob, this is still hand-typed prose, not
# checked against the code -- fixing that would mean adding a canonical exit-code
# registry somewhere in cli/, which no code currently defines and which is out of this
# script's owned paths. What IS in scope, and done below: the codes are the ones a
# `typer.Exit(N)`/`return N` grep across `src/docket/cli/` actually finds today (0, 1,
# 2 only) -- a prior version of this table claimed 2 meant "Missing dependency" and
# listed 3/4/5, none of which any command emits (`docket init`'s own missing-dependency
# check returns 1, and Click's automatic usage-error path is what actually owns 2).
_EXIT_CODES = """\
| Code | Meaning |
|------|---------|
| 0 | Success (includes `approve`/`deny` re-resolving a token to the verdict it already has) |
| 1 | Error (generic; also used by all `_REMOVED` command notices, `approve`/`deny` on an unknown token or one being flipped to the opposite verdict, and `docket init`'s missing-dependency check) |
| 2 | Usage/refusal error: Typer's own automatic response to a missing or invalid argument, `docket harness run`'s `--workspace`/`--task`/preflight refusal, or the internal `_json` bridge's bad or missing verb |

No command emits any other exit code today.
"""

# --- environment-variable introspection ------------------------------------------
#
# A hand-typed markdown blob here would make `--check` prove only that the checked-in
# file matches whatever text a human last typed, never that the text matches what the
# code actually reads. So the *set* of variable names below is scanned out of the
# source tree; only the prose (`_ENV_VAR_ROWS`) is hand-authored, and `render()` raises
# the moment the scanned set and the documented set disagree in either direction -- a
# new `os.environ.get(...)` call with no matching row fails generation instead of
# silently going undocumented.
#
# What is deliberately NOT here: `DOCKET_APPROVAL_MODE` and `DOCKET_PIPELINE_WORKTREE`
# (core/runtime_driver.py) look like environment variables and are named like one, but
# both are documented at their definition as an "internal env-coordinate route" -- a
# plain dict passed caller-to-driver through `run_turn`'s `env` argument, never read from
# the real process environment. Neither name is ever passed to `os.environ.get`/`getenv`,
# so the scan below correctly never finds them; adding either to this table would tell an
# operator that `export`-ing it changes behavior, which it does not.

_BIN_DOCKET = ROOT / "bin" / "docket"

# Real, but not something an operator tunes for docket's own behavior: PATH is the
# ordinary OS search path, read only to build a minimal subprocess environment
# (edges/adapters/toolbox.py, edges/adapters/system.py). Excluded by name, not silently
# dropped, so the exclusion itself is visible to anyone reading this file.
_ENV_SCAN_EXCLUDE = {"PATH"}


def _os_environ_call_name(node: ast.Call) -> str | None:
    """Return the literal name in `os.environ.get(...)`/`os.getenv(...)`/
    `os.environ.pop(...)`/`os.environ.setdefault(...)`, or None if this call
    doesn't match one of those shapes or its first argument isn't a literal."""
    func = node.func
    is_environ_method = (
        isinstance(func, ast.Attribute)
        and func.attr in ("get", "pop", "setdefault")
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "environ"
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "os"
    )
    is_getenv = (
        isinstance(func, ast.Attribute)
        and func.attr == "getenv"
        and isinstance(func.value, ast.Name)
        and func.value.id == "os"
    )
    if not (is_environ_method or is_getenv) or not node.args:
        return None
    arg = node.args[0]
    return arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None


def _os_environ_subscript_name(node: ast.Subscript) -> str | None:
    """Return the literal name in `os.environ["NAME"]` (read or assigned --
    `os.environ["DEBUG"] = "1"` is exactly the shape `--debug` uses)."""
    val = node.value
    if not (
        isinstance(val, ast.Attribute)
        and val.attr == "environ"
        and isinstance(val.value, ast.Name)
        and val.value.id == "os"
    ):
        return None
    sl = node.slice
    return sl.value if isinstance(sl, ast.Constant) and isinstance(sl.value, str) else None


def _optional_int_env_call_name(node: ast.Call) -> str | None:
    """`config._optional_int_env(name)` hides its literal from the scans above --
    the read inside it uses the parameter, not a literal -- so its call sites need
    their own check."""
    if isinstance(node.func, ast.Name) and node.func.id == "_optional_int_env" and node.args:
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def _scan_python_env_names() -> set[str]:
    names: set[str] = set()
    for path in sorted((SRC / "docket").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                found = _os_environ_call_name(node) or _optional_int_env_call_name(node)
                if found:
                    names.add(found)
            elif isinstance(node, ast.Subscript):
                found = _os_environ_subscript_name(node)
                if found:
                    names.add(found)
    return names - _ENV_SCAN_EXCLUDE


def _scan_bin_docket_env_names() -> set[str]:
    """bin/docket is bash, not Python -- a regex pass over `${VAR:-...}`/`${VAR}`
    reads keeps the launcher's own overrides in the checked set too."""
    import re as _re

    text = _BIN_DOCKET.read_text(encoding="utf-8")
    return set(_re.findall(r"\$\{([A-Z][A-Z0-9_]*)(?::?-|\})", text))


def _dispatch_retry_role_names() -> set[str]:
    """`DISPATCH_RETRIES_{role.upper()}` in config.py is built from
    DISPATCH_RETRIES_PER_ROLE's own key set -- read that set back instead of
    re-typing the role names here, so a new role shows up automatically."""
    from docket import config as _config

    return {f"DISPATCH_RETRIES_{role.upper()}" for role in _config.DISPATCH_RETRIES_PER_ROLE}


def _provider_credential_names() -> set[str]:
    """Provider API-key env var names, read from the one provider -> credential-name
    map (core/provider.py, which the llm adapter imports) instead of re-typing them."""
    from docket.core.provider import PROVIDER_CREDENTIAL_NAMES

    names: set[str] = set()
    for credential_names in PROVIDER_CREDENTIAL_NAMES.values():
        names.update(credential_names)
    return names


def _true_env_var_names() -> set[str]:
    """The complete set of environment-variable names the running code actually
    reads -- what `_ENV_VAR_ROWS` below is checked against."""
    return (
        _scan_python_env_names()
        | _scan_bin_docket_env_names()
        | _dispatch_retry_role_names()
        | _provider_credential_names()
    )


# _ENV_VAR_ROWS: (names-this-row-documents, description, default). A tuple of more than
# one name is a row that covers a whole family (the four per-role dispatch-retry
# overrides; the provider API-key names) rather than one row per name, but every name
# the scan finds MUST appear in exactly one row's tuple or render() raises.
_ENV_VAR_ROWS: list[tuple[tuple[str, ...], str, str]] = [
    (
        ("DOCKET_HOME",),
        "Root of everything docket owns — the only state root; no external daemon directory exists",
        "`~/.docket`",
    ),
    (
        ("SITES_DIR",),
        "Default parent directory for project codebases, created by `docket init`'s setup step",
        "`~/Sites`",
    ),
    (("DOCKET_LOG_DIR",), "Directory for docket-owned log files", "`/tmp/docket`"),
    (
        ("TRACES_DIR",),
        "Root of per-session trace JSONL files (`docket trace`)",
        "`$DOCKET_HOME/traces`",
    ),
    (
        ("POLICIES_DIR",),
        "Root of installed/edited policy JSON (`docket policies`, `docket gates`)",
        "`$DOCKET_HOME/policies`",
    ),
    (
        ("APPROVALS_DIR",),
        "Where `docket approve`/`deny`'s approval-token store lives",
        "`$DOCKET_HOME/approvals`",
    ),
    (
        ("SCHEDULE_FILE",),
        "The persisted `docket schedule` registry",
        "`$DOCKET_HOME/docket-schedules.json`",
    ),
    (
        ("RUNS_FILE",),
        "The persisted dispatch-run registry — one record per `dispatch_pod` invocation",
        "`$DOCKET_HOME/docket-runs.json`",
    ),
    (
        ("SESSIONS_DIR",),
        "Root of durable per-session turn history (`core/session.py`)",
        "`$DOCKET_HOME/sessions`",
    ),
    (
        ("MCP_SERVERS_FILE",),
        "Registry of configured external MCP tool servers (`docket mcp servers`)",
        "`$DOCKET_HOME/docket-mcp-servers.json`",
    ),
    (
        ("FLEET_FILE",),
        "Agent registration, channel bindings, gate/isolation flags, provider endpoints, org default model",
        "`$DOCKET_HOME/fleet.json`",
    ),
    (
        ("AUDIT_LOG_MAX_BYTES",),
        "Audit-log rotation threshold (`docket audit`)",
        "`5242880` (5 MiB)",
    ),
    (("SESSION_TIMEOUT",), "Age past which an expired approval is denied (fail-closed)", "`3600`"),
    (
        ("APPROVAL_TIMEOUT",),
        "The async approval-gate window (`core/dispatch.py`'s `require_approval`) — a task waits `waiting_approval`; no process or turn is blocked on it",
        "`900`",
    ),
    (
        ("TOOL_APPROVAL_TIMEOUT",),
        "The in-turn approval wait (`core/approval.py`'s `wait_for_approval`) — blocks a live tool call, so it is far shorter than `APPROVAL_TIMEOUT`",
        "`120`",
    ),
    (
        ("TOOL_APPROVAL_POLL_INTERVAL_S",),
        "How often the in-turn approval wait re-checks the record while blocked",
        "`2`",
    ),
    (
        ("CLAIM_STALE_TIMEOUT",),
        "A pod task claimed longer than this without finishing is presumed crashed and failed by the dispatch sweep",
        "`1800`",
    ),
    (("METRICS_WINDOW",), "Rolling terminal-session count for `docket metrics`", "`50`"),
    (
        ("RUNAWAY_TURNS_THRESHOLD",),
        "Past this many turns, `docket doctor`/`docket cost` flag a session as runaway",
        "`200`",
    ),
    (
        ("RUNAWAY_COST_THRESHOLD",),
        "Past this estimated USD, `docket doctor`/`docket cost` flag a session as runaway",
        "`20`",
    ),
    (
        ("DOCKET_KEY_MAX_AGE_DAYS",),
        "`docket doctor`'s key-hygiene report flags a stored secret STALE past this age — a rotation nudge, never an expiry",
        "`90`",
    ),
    (
        ("TRACE_RETENTION_DAYS",),
        "How long a terminated trace file survives before `docket trace expire` deletes it",
        "`30`",
    ),
    (
        ("TEMPLATE_VERSION",),
        "Workspace-prompt schema version; `docket doctor` flags older agents for rebuild past a bump",
        "`4`",
    ),
    (
        ("CONTEXT_BYTES_PER_TOKEN",),
        "Bytes-per-token estimator behind the static-context guards in `docket maintain check`",
        "`4`",
    ),
    (
        ("CONTEXT_TOKEN_BUDGET",),
        "Soft cap on the static per-turn context (SOUL+AGENTS+TOOLS+HEARTBEAT+MEMORY.md); `docket maintain check` warns past this",
        "`6000`",
    ),
    (
        ("DISTILL_TIMEOUT_S",),
        "Wall-clock bound on `docket maintain distill`'s one driver-backed turn",
        "`120`",
    ),
    (
        ("DISTILL_MAX_INPUT_BYTES",),
        "How much daily-log content goes into a distillation turn's prompt",
        "`49152` (48 KiB)",
    ),
    (
        ("DISPATCH_RETRIES_DEFAULT",),
        "Retry attempts after the first try for a retryable dispatch-hop failure (timeout/`daemon_error` only), for any role with no per-role override",
        "`2`",
    ),
    (
        (
            "DISPATCH_RETRIES_LEAD",
            "DISPATCH_RETRIES_IMPLEMENTER",
            "DISPATCH_RETRIES_REVIEWER",
            "DISPATCH_RETRIES_TESTER",
        ),
        "Per-role override of `DISPATCH_RETRIES_DEFAULT`",
        "same as `DISPATCH_RETRIES_DEFAULT`",
    ),
    (
        ("DISPATCH_RETRY_BACKOFF_S",),
        "Linear backoff base between retries — attempt N waits N times this many seconds",
        "`2`",
    ),
    (
        ("DISPATCH_TURN_TIMEOUT_S",),
        "`docket serve`-only ceiling on a dispatch hop's turn timeout, overriding a pod's own Lead-meta value for serve-triggered dispatches",
        "unset (no serve-wide override)",
    ),
    (
        ("DISPATCH_VERIFY_TIMEOUT_S",),
        "Same as `DISPATCH_TURN_TIMEOUT_S`, for the verify step",
        "unset (no serve-wide override)",
    ),
    (("AGENT_LOOP_MAX_ITERATIONS",), "Hard cap on model round-trips within one turn", "`20`"),
    (
        ("AGENT_LOOP_MAX_TOOL_CALLS",),
        "Hard cap on total tool calls dispatched across one turn",
        "`40`",
    ),
    (
        ("AGENT_LOOP_MAX_CONSECUTIVE_TOOL_DENIALS",),
        "Stops a denial-only loop before it consumes the iteration/tool/token limits",
        "`3`",
    ),
    (
        ("DOCKET_TOOL_MAX_OUTPUT_CHARS",),
        "Ceiling on one tool result's text before it is visibly truncated — tune down for a small-context endpoint",
        "`30000`",
    ),
    (
        ("AGENT_LOOP_WALL_CLOCK_TIMEOUT_S",),
        "Default overall wall-clock budget for one turn with no explicit `LoopConfig`",
        "`300`",
    ),
    (
        ("AGENT_LOOP_TOKEN_BUDGET",),
        "Hard cap on one turn's cumulative measured token usage",
        "`100000`",
    ),
    (
        ("AGENT_LOOP_REQUEST_TIMEOUT_S",),
        "Per-HTTP-call timeout passed to the chat backend",
        "`120`",
    ),
    (
        ("MCP_CLIENT_TIMEOUT_S",),
        "Default per-call bound for an MCP server with no timeout of its own",
        "`10`",
    ),
    (
        ("MCP_CLIENT_MAX_TIMEOUT_S",),
        "Hard ceiling every server-specified MCP timeout is clamped to",
        "`60`",
    ),
    (
        ("FETCH_ALLOWED_DOMAINS",),
        "Comma-separated exact hostnames the `fetch` tool may reach",
        "empty (nothing allowed until opted in)",
    ),
    (
        ("FETCH_MAX_RESPONSE_BYTES",),
        "Response-body cap for the `fetch` tool before truncation",
        "`200000`",
    ),
    (("FETCH_TIMEOUT_S",), "Default per-call wall-clock bound for the `fetch` tool", "`15`"),
    (
        ("TELEGRAM_POLL_TIMEOUT_S",),
        "The Telegram-side long-poll wait passed to `getUpdates`",
        "`25`",
    ),
    (
        ("TELEGRAM_REQUEST_TIMEOUT_S",),
        "This process's own socket timeout for Telegram calls — must exceed `TELEGRAM_POLL_TIMEOUT_S`",
        "`35`",
    ),
    (
        ("DOCKET_SECRETS_BACKEND",),
        "Stored-secret backend: `file` (default, `secrets.json`) or `keyring` (secret-tool/libsecret)",
        "`file`",
    ),
    (
        ("DOCKET_KEYRING_SERVICE",),
        "The libsecret service name secrets are stored under when `DOCKET_SECRETS_BACKEND=keyring`",
        "`docket-cli`",
    ),
    (("DOCKET_NO_TRACE",), "Set to `1` to disable trace-store writes", "unset (tracing on)"),
    (
        ("DOCKET_SANDBOX_IMAGE",),
        "Image for the Docker exec-jail (`docket gates isolate on`)",
        "`alpine:3.20`",
    ),
    (
        ("DOCKET_SANDBOX_BACKEND",),
        "Force or disable the sandbox backend (`docker`/`bwrap`/`none`) regardless of what is actually installed",
        "auto-detected (docker > bwrap > none)",
    ),
    (("EDITOR",), "Text editor for `docket edit`, checked before `VISUAL`", "`nano`"),
    (("VISUAL",), "Fallback text editor for `docket edit` when `EDITOR` is unset", "`nano`"),
    (
        ("DOCKET_SERVE_TOKEN",),
        "Fix `docket serve`'s bearer token instead of generating one per run",
        "unset (random)",
    ),
    (
        ("DOCKET_LLM_BASE_URL",),
        "Process-wide override that points every model at one endpoint (local dev, tests without stored config)",
        "unset",
    ),
    (
        ("DOCKET_LLM_API_KEY",),
        "Process-wide API key override, paired with `DOCKET_LLM_BASE_URL`",
        "unset",
    ),
    (
        (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GOOGLE_AI_API_KEY",
            "OPENROUTER_API_KEY",
            "AI_GATEWAY_API_KEY",
            "VERCEL_OIDC_TOKEN",
        ),
        "Per-provider API key, checked when neither `DOCKET_LLM_API_KEY` nor a stored fleet key is set; an unset one is also checked against docket's own secret store (`docket keys add`). An unlisted provider falls back to `<PROVIDER>_API_KEY`",
        "unset",
    ),
    (
        ("DOCKET_CLI_ROOT",),
        "Repo root override used by the `bin/docket` launcher to select which project to `uv run` against",
        "package/launcher location",
    ),
    (
        ("DOCKET_PYTHON",),
        "Explicit interpreter for `bin/docket` to exec (e.g. a Homebrew venv)",
        "unset (auto-resolved)",
    ),
]


def _check_env_var_rows_match_scan() -> None:
    documented: set[str] = set()
    for names, _desc, _default in _ENV_VAR_ROWS:
        documented.update(names)
    scanned = _true_env_var_names()
    undocumented = sorted(scanned - documented)
    stale = sorted(documented - scanned)
    if undocumented:
        raise SystemExit(
            f"gen_cli_docs: environment variable(s) read by the code but missing from "
            f"_ENV_VAR_ROWS: {undocumented} — add a row in scripts/gen_cli_docs.py"
        )
    if stale:
        raise SystemExit(
            f"gen_cli_docs: _ENV_VAR_ROWS names variable(s) no code reads any more: "
            f"{stale} — remove them from scripts/gen_cli_docs.py"
        )


def _render_env_vars_table() -> str:
    _check_env_var_rows_match_scan()
    lines = ["| Variable | Description | Default |", "|----------|-------------|---------|"]
    for names, desc, default in _ENV_VAR_ROWS:
        var_cell = ", ".join(f"`{n}`" for n in names)
        lines.append(f"| {var_cell} | {desc} | {default} |")
    lines.append("")
    lines.append(
        "There is **no** environment kill switch for the audit log — a prior `DOCKET_NO_AUDIT` "
        "escape hatch was removed because it let anyone silently disable docket's only tamper "
        "record; audit writes are unconditional and best-effort (a write failure never raises, "
        "but it also can't be turned off)."
    )
    return "\n".join(lines) + "\n"


_TIPS = """\
### Interactive Pickers

If you have fzf installed, omit the agent-id for fuzzy search:

```bash
docket info      # Opens fzf picker
docket delete    # Opens fzf picker
docket logs      # Opens fzf picker
```

### Batch Operations

Use bash loops for batch operations:

```bash
# Reset all agents
for id in $(docket list | awk '{print $1}' | tail -n +2); do
  docket maintain "$id" clean
done

# Cheaper models fleet-wide: change the policy once — every
# policy-following agent updates automatically (pins are untouched)
docket models preset openrouter-free
```

### Cost Monitoring

Track daily costs:

```bash
# Add to crontab
0 23 * * * docket cost >> ~/docket-costs-$(date +%Y-%m).log
```

### Backup Strategy

Regular backups:

```bash
# Backup script
#!/bin/bash
tar -czf ~/backups/docket-$(date +%s).tar.gz \\
  ~/.docket/fleet.json \\
  ~/.docket/workspaces/

# Or a single-file fleet snapshot
docket snapshot -o ~/backups/fleet-$(date +%s).json
```
"""

_NEXT_STEPS = """\
- [Agent Teams (Pods)](AGENT-TEAMS.md)
- [Workflow Guide](WORKFLOW-GUIDE.md)
- [Main README](../README.md)
"""


def render(check_only: bool = False) -> str:
    group = _load_click_group()
    commands = {
        name: cmd for name, cmd in group.commands.items() if not getattr(cmd, "hidden", False)
    }
    aliases, removed = _load_aliases_and_removed()

    aliases_by_target: dict[str, list[str]] = {}
    for alias, target in aliases.items():
        aliases_by_target.setdefault(target, []).append(alias)
    for target in aliases_by_target:
        aliases_by_target[target].sort()

    grouped_names = {name for _heading, names in GROUPS for name in names}
    remaining = sorted(set(commands) - grouped_names - {"help"})
    if remaining:
        raise SystemExit(
            f"gen_cli_docs: command(s) not assigned to a GROUPS section: {remaining} "
            "— add them to GROUPS in scripts/gen_cli_docs.py"
        )
    stale = sorted(grouped_names - set(commands))
    if stale:
        raise SystemExit(
            f"gen_cli_docs: GROUPS names command(s) no longer in the registry: {stale} "
            "— remove them from scripts/gen_cli_docs.py"
        )

    lines: list[str] = []
    lines.append("# Command Reference\n")
    lines.append(
        "Generated from the live Typer registry by `scripts/gen_cli_docs.py` — do not "
        "hand-edit. Regenerate with `uv run python scripts/gen_cli_docs.py` after changing "
        "any CLI help string; `scripts/gen_cli_docs.py --check` fails CI on drift.\n"
    )
    lines.append(
        "Complete reference for all docket commands, rendered from each command's own "
        "`--help` text so the CLI and this document can never drift apart.\n"
    )

    lines.append("## Table of Contents\n")
    for heading, _names in GROUPS:
        lines.append(f"- [{heading}](#{_slug(heading)})")
    for heading in (
        "Global Options",
        "Command Aliases",
        "Removed Commands",
        "Exit Codes",
        "Environment Variables",
        "Tips & Tricks",
        "Next Steps",
    ):
        lines.append(f"- [{heading}](#{_slug(heading)})")
    lines.append("")

    for heading, names in GROUPS:
        lines.append(f"## {heading}\n")
        for name in names:
            lines.append(_render_command(name, commands[name], aliases_by_target))
            lines.append("\n---\n")

    lines.append("## Global Options\n")
    help_cmd = commands["help"]
    help_body = _render_help_body(help_cmd.help or "")
    lines.append(_GLOBAL_OPTIONS.format(help_body=help_body))
    lines.append("\n---\n")

    lines.append("## Command Aliases\n")
    lines.append(
        "Every alias below is drawn directly from `src/docket/__main__.py`'s `_ALIASES` map — "
        "the single source of truth. `docket <alias>` rewrites to `docket <command>` before "
        "argument parsing.\n"
    )
    lines.append("| Alias | Command |")
    lines.append("|-------|---------|")
    for alias in sorted(aliases):
        lines.append(f"| `{alias}` | `{aliases[alias]}` |")
    lines.append("")
    unaliased = sorted(
        name for name in commands if name not in aliases_by_target and name != "help"
    )
    lines.append("`" + "`, `".join(unaliased) + "`, `help` have no alias.\n")
    lines.append("\n---\n")

    lines.append("## Removed Commands\n")
    lines.append(
        "These command names are **not aliases** — typing them prints a migration notice and "
        "exits 1 (`src/docket/__main__.py`'s `_REMOVED` map). They do not run anything.\n"
    )
    lines.append("| Removed name | Notice |")
    lines.append("|---|---|")
    seen_messages: dict[tuple[str, ...], list[str]] = {}
    order: list[tuple[str, ...]] = []
    for name, messages in removed.items():
        if messages not in seen_messages:
            seen_messages[messages] = []
            order.append(messages)
        seen_messages[messages].append(name)
    for messages in order:
        names = ", ".join(f"`{n}`" for n in sorted(seen_messages[messages]))
        notice = " ".join(messages).replace("|", "\\|")
        lines.append(f"| {names} | {notice} |")
    lines.append("")
    lines.append("\n---\n")

    lines.append("## Exit Codes\n")
    lines.append(_EXIT_CODES)
    lines.append("\n---\n")

    lines.append("## Environment Variables\n")
    lines.append(_render_env_vars_table())
    lines.append("\n---\n")

    lines.append("## Tips & Tricks\n")
    lines.append(_TIPS)
    lines.append("\n---\n")

    lines.append("## Next Steps\n")
    lines.append(_NEXT_STEPS)

    text = "\n".join(lines)
    # Collapse runs of 3+ blank lines and ensure a single trailing newline.
    while "\n\n\n\n" in text:
        text = text.replace("\n\n\n\n", "\n\n\n")
    return text.rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    check_only = "--check" in argv

    rendered = render(check_only=check_only)

    if check_only:
        current = COMMANDS_MD.read_text(encoding="utf-8") if COMMANDS_MD.exists() else None
        if current == rendered:
            print(f"gen_cli_docs: {COMMANDS_MD.relative_to(ROOT)} is up to date.")
            return 0
        print(
            f"gen_cli_docs: {COMMANDS_MD.relative_to(ROOT)} is STALE — "
            "run `uv run python scripts/gen_cli_docs.py` to regenerate.",
            file=sys.stderr,
        )
        return 1

    COMMANDS_MD.write_text(rendered, encoding="utf-8")
    print(f"gen_cli_docs: wrote {COMMANDS_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
