# Input Validation Specification

**Version**: 1.1.0
**Status**: Complete
**Last Updated**: 2026-06-24

## Purpose

This specification defines all input validation rules for docket CLI commands to ensure data
integrity, security, and proper error handling.

Since the Bash→Python cutover (M6), docket is a Python package under `src/docket/` organised
into three layers — `cli/ → core/ → edges/`. Validation lives in the **`core/`** layer
(Pydantic models in `core/models.py`, typed helpers in `core/utils.py` /
`core/models_policy.py`), is surfaced to the user from the **`cli/`** layer via
`typer.Exit` and the Rich helpers in `src/docket/ui.py` (`info`/`success`/`warn`/`error`),
and all side-effecting I/O is funnelled through the **`edges/`** layer (docket-owned JSON via
`src/docket/edges/store.py`; OpenClaw config only via the ACL
`src/docket/edges/adapters/openclaw.py`). The rules below are the **contract**; the Python
snippets and module pointers show how that contract is enforced today.

## Rules

Validation rules are grouped by input field. Each category states the field, the commands
that consume it, the RFC 2119 rule set, and the reference implementation (Python module /
function or Pydantic model).

### 1. Agent ID Validation

**Field**: agent-id
**Used By**: add, info, delete, maintain, profile, scope, workflow, pod

**Rules**:
- **MUST** match pattern: `^[a-z0-9][a-z0-9-]*[a-z0-9]$`
- **MUST** be between 3 and 50 characters
- **MUST NOT** contain consecutive hyphens
- **MUST NOT** be a reserved word
- **MUST** be unique (for creation)

**Reserved Words**:
- system, docket, openclaw, manager
- admin, root, daemon, service
- config, settings, help, version

**Reference**: ids are derived from a display name by the slugifier in the `add` flow
(`src/docket/cli/__init__.py`, `_slugify` → `re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")`),
then checked for the format/length/reserved-word rules and for uniqueness against
`config.PROJECTS_DIR` (`~/.openclaw/workspaces/projects/<agent-id>/`). The canonical
predicate is expressed as:

```python
import re
import typer
import docket.config as cfg
from docket import ui

_AGENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
_RESERVED = frozenset(
    {
        "system", "docket", "openclaw", "manager",
        "admin", "root", "daemon", "service",
        "config", "settings", "help", "version",
    }
)


def validate_agent_id(agent_id: str, *, check_exists: bool = False) -> None:
    """Raise typer.Exit(1) (after ui.error) if agent_id is not a valid id."""
    if not 3 <= len(agent_id) <= 50:
        ui.error("Agent ID must be 3-50 characters")
        raise typer.Exit(1)
    if not _AGENT_ID_RE.match(agent_id):
        ui.error("Agent ID must be lowercase alphanumeric with dashes")
        raise typer.Exit(1)
    if "--" in agent_id:
        ui.error("Agent ID cannot contain consecutive hyphens")
        raise typer.Exit(1)
    if agent_id in _RESERVED:
        ui.error(f"Agent ID '{agent_id}' is reserved")
        raise typer.Exit(1)
    # Uniqueness — a project dir or its pod Lead dir already existing is a conflict.
    if check_exists and (
        (cfg.PROJECTS_DIR / agent_id).is_dir()
        or (cfg.PROJECTS_DIR / f"{agent_id}-lead").is_dir()
    ):
        ui.error(f"A project or pod '{agent_id}' already exists.")
        raise typer.Exit(1)
```

### 2. Path Validation

**Field**: codebase-path, file-path
**Used By**: add, workflow

**Rules**:
- **MUST** be absolute path or start with ~
- **MUST** exist (for codebase)
- **MUST** be readable
- **MUST NOT** be a system directory
- **MUST** resolve symlinks

**Forbidden Paths**:
- /, /bin, /sbin, /usr, /lib, /lib64
- /etc, /boot, /dev, /proc, /sys
- /root, /var/log

**Reference**: paths are handled with `pathlib.Path` — `Path.expanduser()` for tilde,
`Path.resolve()` to make absolute and resolve symlinks, `.is_dir()`/`.is_file()`/`os.access`
for existence and readability. The forbidden-directory check guards against pointing an agent
at a system root:

```python
import os
from pathlib import Path
import typer
from docket import ui

_FORBIDDEN_DIRS = {
    Path(p)
    for p in (
        "/", "/bin", "/sbin", "/usr", "/lib", "/lib64",
        "/etc", "/boot", "/dev", "/proc", "/sys", "/root", "/var/log",
    )
}


def validate_path(raw: str, *, must_exist: bool = True, kind: str = "dir") -> Path:
    """Return the resolved Path or raise typer.Exit(1)."""
    path = Path(raw).expanduser().resolve()  # tilde + absolute + symlinks
    if path in _FORBIDDEN_DIRS:
        ui.error(f"Cannot use system directory: {path}")
        raise typer.Exit(1)
    if must_exist:
        ok = path.is_dir() if kind == "dir" else path.is_file()
        if not ok:
            ui.error(f"{'Directory' if kind == 'dir' else 'File'} not found: {path}")
            raise typer.Exit(1)
        if not os.access(path, os.R_OK):
            ui.error(f"Permission denied: {path}")
            raise typer.Exit(1)
    return path
```

### 3. Model Validation

**Field**: model, profile
**Used By**: add, profile, models

**Rules**:
- **MUST** be a well-formed provider/model id matching `^[a-z0-9_-]+/[A-Za-z0-9._:/-]+$`
  (e.g. `anthropic/claude-sonnet-4-6`), OR a known alias
- An unknown-but-well-formed id is **accepted** with a warning that it is absent from
  docket's pricing table (cost will render as `n/a`)
- A malformed id **MUST** be rejected with a hard error listing the current role policy
- Tier names (economy/standard/premium) are **deprecated aliases**: accepted with a
  deprecation warning that resolves them through internal rank anchors to a concrete
  provider/model id — they are not the validation surface

**Reference**: `validate_model()` in `src/docket/core/models_policy.py` returns
`(canonical_model, warnings)` and raises `ValueError` on a malformed id (the `cli/` layer
converts that into a `ui.error` + `typer.Exit`). The id grammar is the module-level
`_MODEL_ID_RE = re.compile(r"^[a-z0-9_-]+/[A-Za-z0-9._:/-]+$")`. Resolution order is:

1. deprecated tier name → its rank anchor (with a deprecation warning);
2. known alias → its resolved id (warned);
3. well-formed `provider/model` id → accepted (warned only if unpriced);
4. otherwise → `ValueError` with the current role policy listing.

```python
from docket.core.models_policy import validate_model

canonical, warnings = validate_model("anthropic/claude-sonnet-4-6")
# canonical == "anthropic/claude-sonnet-4-6"; warnings == [] when priced.
# validate_model("gpt-5") raises ValueError (no provider/ prefix → malformed).
```

### 4. Numeric Validation

**Field**: level, period, timeout
**Used By**: maintain, cost, various

**Rules**:
- **MUST** be a positive integer
- **MUST** be within the allowed range
- **MUST NOT** have leading zeros

**Ranges**:
- Reset level: 1-3
- Cost period: 1-365 days
- Timeout: 1-3600 seconds

**Reference**: numeric arguments are declared as typed `typer` options/arguments (`int`),
so Typer rejects non-numeric input before the command body runs. Range and leading-zero
checks are enforced in the command (or via a small helper) and surfaced through `ui.error` +
`typer.Exit`:

```python
import typer
from docket import ui


def validate_number(raw: str, *, lo: int, hi: int, name: str = "value") -> int:
    """Return the int in [lo, hi] or raise typer.Exit(1)."""
    if not raw.isdigit():
        ui.error(f"{name} must be a number")
        raise typer.Exit(1)
    if len(raw) > 1 and raw[0] == "0":
        ui.error(f"{name} cannot have leading zeros")
        raise typer.Exit(1)
    value = int(raw)
    if not lo <= value <= hi:
        ui.error(f"{name} must be between {lo} and {hi}")
        raise typer.Exit(1)
    return value
```

### 5. Session Key Validation

**Field**: session-key, project-key
**Used By**: scope

**Rules**:
- **MUST** follow format: `agent:<id>:<project>`
- **MUST** have a valid agent ID component
- **MUST** have a valid project component
- Project **MUST** be alphanumeric + dash (same grammar as an agent id)
- **MUST NOT** exceed 100 characters total

**Reference**: the session key is composed, never free-typed — `docket scope <id> set
<project-key>` builds `session_key = f"agent:{aid}:{project_key}"`
(`src/docket/cli/__init__.py`, the `scope` command) and persists it via the ACL
(`_oc.meta_set` / `_oc.sync_session_key`). When a key is parsed back, the format and its two
components are validated against the agent-id grammar:

```python
import re
import typer
from docket import ui

_SESSION_KEY_RE = re.compile(r"^agent:([a-z0-9][a-z0-9-]*[a-z0-9]):([a-z0-9][a-z0-9-]*[a-z0-9])$")


def validate_session_key(key: str) -> tuple[str, str]:
    """Return (agent_id, project) or raise typer.Exit(1)."""
    if len(key) > 100:
        ui.error("Session key too long (max 100 characters)")
        raise typer.Exit(1)
    m = _SESSION_KEY_RE.match(key)
    if not m:
        ui.error("Session key must follow format: agent:<id>:<project>")
        raise typer.Exit(1)
    return m.group(1), m.group(2)
```

### 6. Command Action Validation

**Field**: action / sub-command
**Used By**: scope, workflow, team, keys, pod

**Rules**:
- **MUST** be from the allowed action list for that command
- Case sensitive
- **MUST** have the required arguments

**Actions by Command**:
- scope: show, set, reset
- workflow: create, list, show, delete, run
- team: status, delegate, queue, done
- keys: list, add, rotate, remove, sync
- pod: (show), add, remove

**Reference**: sub-commands and their required arguments are modelled directly in the Typer
command signatures (`src/docket/cli/__init__.py` and the split groups under
`src/docket/cli/_*.py`). The action is matched in the command body and a missing required
argument aborts via `ui.error` + `typer.Exit(1)` — e.g. the `scope` command:

```python
# inside the `scope` command (cli/__init__.py)
action = sub or "show"
if action == "set":
    if not project_key:
        ui.error(f"Project key required. Usage: docket scope {aid} set <project-key>")
        raise typer.Exit(1)
    ...
elif action not in {"show", "set", "reset"}:
    ui.error(f"Invalid scope action: {action}")
    raise typer.Exit(1)
```

### 7. API Key Validation

**Field**: api-key
**Used By**: keys

**Rules**:
- Key **name** **MUST** match `^[A-Z][A-Z0-9_]*$` (UPPERCASE_WITH_UNDERSCORES)
- Key **value** **MUST NOT** be empty
- Value **SHOULD** match the provider's expected prefix / minimum length (a mismatch is a
  non-fatal warning, not a hard reject — keys from new providers must still be storable)

**Provider Formats** (`_KEY_PREFIXES` in `src/docket/cli/__init__.py`, `(prefix, min_len)`):
- `ANTHROPIC_API_KEY`: prefix `sk-ant-`, min length 40
- `OPENAI_API_KEY`: prefix `sk-`, min length 40
- `GOOGLE_AI_API_KEY`: prefix `AIza`
- `OPENROUTER_API_KEY`: prefix `sk-or-`

**Reference**: `_keys_add()` enforces the name grammar and non-empty value
(`ui.error` + `typer.Exit`), then calls `_validate_key_format()`, whose format mismatch is
surfaced as a `ui.warn`:

```python
# src/docket/cli/__init__.py
_KEY_PREFIXES: dict[str, tuple[str, int]] = {
    "ANTHROPIC_API_KEY": ("sk-ant-", 40),
    "OPENAI_API_KEY": ("sk-", 40),
    "GOOGLE_AI_API_KEY": ("AIza", 0),
    "OPENROUTER_API_KEY": ("sk-or-", 0),
}


def _validate_key_format(name: str, value: str) -> tuple[bool, str]:
    """Return (ok, reason). reason is empty when ok."""
    if name in _KEY_PREFIXES:
        prefix, min_len = _KEY_PREFIXES[name]
        if not value.startswith(prefix):
            return False, f"should start with '{prefix}'"
        if min_len and len(value) < min_len:
            return False, f"too short (< {min_len} chars)"
    return True, ""
```

## Functions

The reference implementations above define the canonical validation surface. Every command
MUST route untrusted input through the matching validator (typed `typer` parameter, Pydantic
model, or `core/` helper) before acting on it. Validators report failure by emitting a
`ui.error`/`ui.warn` and raising `typer.Exit` (or, in `core/`, raising `ValueError` for the
`cli/` layer to translate).

| Function / model | Module | Validates | Returns |
|------------------|--------|-----------|---------|
| `validate_agent_id` (id rule above) | `core` / `cli` add flow | Agent ID format, length, reserved words, uniqueness | `None`, or `typer.Exit(1)` |
| `validate_path` (path rule above) | `core` helper | Tilde/absolute path, existence, readability, forbidden dirs | resolved `Path`, or `typer.Exit(1)` |
| `validate_model(model)` | `core/models_policy.py` | Provider/model id grammar, aliases, deprecated tiers | `(canonical, warnings)`, or raises `ValueError` |
| `validate_number(raw, lo, hi, name)` | `cli` (typed `int` params) | Positive integer within range, no leading zeros | `int`, or `typer.Exit(1)` |
| `validate_session_key(key)` | `core` helper | `agent:<id>:<project>` format and components | `(agent_id, project)`, or `typer.Exit(1)` |
| action matching | `cli/__init__.py`, `cli/_*.py` | Action is in the command's allowed set with required args | proceeds, or `typer.Exit(1)` |
| `_validate_key_format(name, value)` | `cli/__init__.py` | Provider prefix / min length | `(ok, reason)` — caller warns on mismatch |
| `AgentMeta` | `core/models.py` | Whole `.docket-meta.json` record (kind/scope/type/model/keys) | parsed model, or `pydantic.ValidationError` |

The **`AgentMeta`** Pydantic model in `src/docket/core/models.py` is the structural validator
for an agent's persisted metadata: it constrains `kind`/`type`/`model_source`/`scope` to their
enums and backfills `scope` for legacy records. Records are read/written only through
`src/docket/edges/store.py`.

### Boundary sanitization (no shell, no hand-rolled JSON)

The Python core does **not** shell out with interpolated input and does **not** hand-build
JSON strings, so the old `sanitize_for_shell` / `escape_json_value` helpers are obsolete:

- **Shell injection**: every external call goes through typed argv wrappers in
  `src/docket/edges/adapters/system.py` (`subprocess.run([...])` with an argument **list** —
  never `shell=True`), so user input can never be interpreted by a shell.
- **JSON escaping**: all docket-owned JSON is serialised by the standard library via
  `src/docket/edges/store.py` (`json` with atomic write + `filelock` + `.bak` rotation +
  `0600` perms); OpenClaw config is serialised the same way behind the ACL
  `src/docket/edges/adapters/openclaw.py`. Escaping is the encoder's job.
- **Path traversal**: agent workspaces are addressed by validated agent id under
  `config.PROJECTS_DIR` (`~/.openclaw/workspaces/projects/<agent-id>/`). To confine a
  user-supplied path to a base, resolve and check containment with `pathlib`:

```python
from pathlib import Path
import typer
from docket import ui
import docket.config as cfg


def confine_to_base(raw: str, base: Path = cfg.PROJECTS_DIR) -> Path:
    """Return a resolved path proven to live under *base*, else typer.Exit(1)."""
    path = Path(raw).expanduser().resolve()
    base = base.resolve()
    if base not in path.parents and path != base:
        ui.error("Path traversal detected")
        raise typer.Exit(1)
    return path
```

### Error message conventions

Errors are emitted through the Rich helpers in `src/docket/ui.py`
(`info`/`success`/`warn`/`error`/`fail`) and the command aborts by raising `typer.Exit(1)`.
There is no Bash-style `validation_error` formatter — the convention is a single
`ui.error("<what failed> …")` line (optionally followed by a usage hint), then `typer.Exit`.

| Validation | Error Message | Suggestion |
|------------|---------------|------------|
| Agent ID format | "Agent ID must be lowercase alphanumeric with dashes" | "Example: my-project-1" |
| Path not found | "Directory not found: `<path>`" | "Check the path exists and is readable" |
| Invalid model | "Invalid model: `'<id>'`" | "Use a full provider/model ID, e.g. anthropic/claude-sonnet-4-6" |
| Number range | "level must be between 1 and 3" | "Use 1 for light, 2 for deep, 3 for complete" |

## Testing

Validation is covered by the **pytest** suite under `tests/python/` (the historical Bash
harness `tests/unit/test-validation.sh` no longer exists). Run it with:

```bash
uv run pytest
```

Data-layer and metadata validation (`AgentMeta`, store round-trips, scope backfill) is
exercised in `tests/python/test_m2_data_layer.py`; command-level argument and action
validation is exercised across the `test_m3_commands.py` / `test_m4_*.py` waves, with
model-id validation in the policy tests. Lint, format, and strict type checks gate CI
alongside the suite:

```bash
uv run pytest               # unit/integration suite (tests/python/)
uv run ruff check .         # lint
uv run ruff format --check .  # format
uv run mypy src             # strict type check
```

Representative cases the suite asserts (expressed as pytest, mirroring the old assertions):

```python
import pytest


@pytest.mark.parametrize(
    "agent_id",
    ["test-agent-1", "abc123"],  # valid: dashes, alphanumeric
)
def test_agent_id_valid(agent_id):
    assert _AGENT_ID_RE.match(agent_id) and agent_id not in _RESERVED


@pytest.mark.parametrize(
    "agent_id",
    ["", "a", "Test-Agent", "test--agent", "-test", "test-", "system"],
    # invalid: empty, too short, uppercase, consecutive dashes, leading/
    # trailing dash, reserved word
)
def test_agent_id_invalid(agent_id):
    with pytest.raises(SystemExit):  # typer.Exit
        validate_agent_id(agent_id)


def test_model_id_rejects_bare_name():
    import pytest
    from docket.core.models_policy import validate_model

    with pytest.raises(ValueError):
        validate_model("gpt-5")  # no provider/ prefix → malformed
    assert validate_model("anthropic/claude-sonnet-4-6")[0] == "anthropic/claude-sonnet-4-6"
```

## Performance

### Validation Timing

These are regex/`pathlib`/`int` checks with negligible cost; the only one that touches the
filesystem is path/uniqueness validation:

- Agent ID (regex + reserved set): < 1ms
- Path validation (`resolve` + `is_dir` + `os.access`): < 10ms
- Model validation (regex + dict lookups): < 1ms
- Session key (regex): < 1ms
- API key format (prefix/length): < 5ms

### Caching

Validation is cheap and ID-keyed, so results are not memoised in a cache; the meaningful I/O
caches in docket sit one layer down in `core/` (e.g. the `.cost-index.json` /
`.cost-history.json` incremental indexes in `core/utils.py`, keyed by file `(mtime, size)`
signatures), not in the validators. Persisted reads that validators depend on go through
`src/docket/edges/store.py`, which already serialises access with a `filelock`.

## Changelog

### Version 1.1.0 (2026-06-24)
- Ported the spec from Bash to the Python reality after the Bash→Python (M6) cutover.
- Replaced the 13 Bash code blocks with Python that reflects how docket validates today
  (typed `typer` params, `core/` helpers, the `AgentMeta` Pydantic model, `validate_model`),
  or with prose + a pointer to the real module where a faithful snippet would be speculative.
- Mapped `WORKSPACES_DIR` → `config.PROJECTS_DIR` (`~/.openclaw/workspaces/projects/...`);
  errors now go through `src/docket/ui.py` + `typer.Exit` instead of Bash `error()`.
- Replaced the obsolete shell-injection / JSON-escaping helpers with the real boundaries
  (argv-list `subprocess` in `edges/adapters/system.py`, stdlib `json` via `edges/store.py`).
- Model validation is now provider/model-id based (`^[a-z0-9_-]+/...`); economy/standard/
  premium are documented as deprecated aliases, not the validation surface.
- Pointed Testing at the pytest suite (`tests/python/`, `uv run pytest`) instead of the
  removed `tests/unit/test-validation.sh`.
- All validation **rules/contract** (agent-id grammar & length, path & forbidden dirs,
  numeric ranges, `agent:<id>:<project>` session key, action allowlists, API-key checks)
  are unchanged.

### Version 1.0.0 (2024-01-20)
- Complete input validation specification
- All field types covered
- Sanitization rules defined
- Error message standards
- Performance requirements
