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
            "serve",
            "completions",
            "snapshot",
            "mcp",
        ],
    ),
    ("Security & Audit", ["gates", "audit", "policies", "approve", "deny"]),
    ("Observability Commands", ["runs", "trace", "metrics"]),
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

Reserved compatibility flag. The parser accepts `--debug`, but no command currently reads the
result or emits additional diagnostic output. Do not rely on it for troubleshooting; use the
command's normal error output, `docket doctor`, traces, and audit records instead.

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

_EXIT_CODES = """\
| Code | Meaning |
|------|---------|
| 0 | Success (includes `approve`/`deny` re-resolving a token to the verdict it already has) |
| 1 | Error (generic; also used by all `_REMOVED` command notices, and `approve`/`deny` on an unknown token or one being flipped to the opposite verdict) |
| 2 | Missing dependency |
| 3 | Invalid argument |
| 4 | Permission denied |
| 5 | Service failure |
"""

_ENV_VARS = """\
| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Set by `--debug`; currently read by no command (reserved) | `0` |
| `EDITOR` | Text editor for `docket edit` | `vi` |
| `DOCKET_HOME` | Root of everything docket owns — the only state root; no external daemon directory exists | `~/.docket` |
| `AUDIT_LOG_MAX_BYTES` | Audit-log rotation threshold (`docket audit`) | `5242880` (5 MiB) |
| `APPROVALS_DIR` | Where `docket approve`/`deny`'s approval-token store lives | `$DOCKET_HOME/approvals` |
| `FETCH_ALLOWED_DOMAINS` | Comma-separated exact hostnames the `fetch` tool may reach | empty (nothing allowed until opted in) |
| `DOCKET_NO_TRACE` | Set to `1` to disable trace-store writes | unset (tracing on) |
| `DOCKET_SERVE_TOKEN` | Fix `docket serve`'s bearer token instead of generating one per run | unset (random) |
| `DOCKET_CLI_ROOT` | Repo root override used by the `bin/docket` launcher to select which project to `uv run` against | package/launcher location |
| `DOCKET_PYTHON` | Explicit interpreter for `bin/docket` to exec (e.g. a Homebrew venv) | unset (auto-resolved) |

There is **no** environment kill switch for the audit log — a prior `DOCKET_NO_AUDIT` escape
hatch was removed because it let anyone silently disable docket's only tamper record; audit
writes are unconditional and best-effort (a write failure never raises, but it also can't be
turned off).
"""

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
    lines.append(_ENV_VARS)
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
