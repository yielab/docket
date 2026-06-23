"""docket policies — manage and test guardrail policies (T5.3 port of policies.sh).

  docket policies list               List installed policies
  docket policies show <id>          Show one policy
  docket policies init               Install baseline policies to $POLICIES_DIR
  docket policies test <hook> <role> "<text>"   Dry-run the evaluator

``run_policies(sub, *, args)`` returns the process exit code. Policy files are
docket-owned artefacts read/written directly (not openclaw config).
"""

from __future__ import annotations

import json
import os
import shutil

import docket.config as _cfg
from docket import ui
from docket.core import policy as _policy

_VALID_HOOKS = ("pre_input", "pre_tool_call", "pre_output")


def _help() -> int:
    ui.header("docket policies")
    ui.console.print()
    ui.console.print("  docket policies list                        List installed policies")
    ui.console.print("  docket policies show <id>                   Show one policy")
    ui.console.print("  docket policies init                        Install baseline policies")
    ui.console.print('  docket policies test <hook> <role> "<text>" Dry-run evaluator')
    ui.console.print()
    ui.console.print(f"  Policy directory: {_cfg.POLICIES_DIR}")
    ui.console.print("  Hooks: pre_input | pre_tool_call | pre_output")
    ui.console.print("  Actions: allow | warn | redact | require_approval | block")
    ui.console.print()
    return 0


def _list() -> int:
    ui.header("Guardrail Policies")
    ui.console.print()

    files = _policy.policy_files()
    if not files:
        ui.warn("No policies installed.")
        ui.info("Run: docket policies init")
        ui.console.print()
        return 0

    # Data rows are emitted with plain print() so bracketed text from policy
    # fields is never parsed as Rich markup.
    print(f"  {'ID':<30} {'HOOK':<16} {'ACTION':<16} DESCRIPTION")
    print(f"  {'─' * 80}")
    for f in files:
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
            pid = str(p.get("id", "?"))[:28]
            hook = str(p.get("hook", "?"))[:14]
            act = str(p.get("action", "?"))[:14]
            desc = str(p.get("description", ""))[:45]
            print(f"  {pid:<30} {hook:<16} {act:<16} {desc}")
        except Exception as exc:
            print(f"  [parse error: {exc}]")
    ui.console.print()
    ui.dim(f"  Policy files in {_cfg.POLICIES_DIR}")
    ui.console.print()
    return 0


def _show(args: list[str]) -> int:
    if not args or not args[0]:
        ui.error("Usage: docket policies show <id>")
        return 1
    target = args[0]

    found = None
    for f in _policy.policy_files():
        try:
            fid = json.loads(f.read_text(encoding="utf-8")).get("id", "")
        except Exception:
            fid = ""
        if fid == target:
            found = f
            break

    if found is None:
        ui.fail(f"Policy not found: {target}")
        return 1

    # python3 -m json.tool: re-serialise the parsed JSON, indented. Use plain
    # print() so bracketed regex patterns aren't parsed as Rich markup.
    parsed = json.loads(found.read_text(encoding="utf-8"))
    print(json.dumps(parsed, indent=4))
    return 0


def _init() -> int:
    template_dir = _cfg.policy_templates_dir()
    if not template_dir.is_dir():
        ui.fail(f"Policy templates not found at {template_dir}")
        return 1

    _cfg.POLICIES_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(_cfg.POLICIES_DIR, 0o700)

    installed = 0
    skipped = 0
    for f in sorted(template_dir.glob("*.json")):
        dest = _cfg.POLICIES_DIR / f.name
        if dest.exists():
            ui.dim(f"  skip (exists): {f.name}")
            skipped += 1
        else:
            shutil.copy(f, dest)
            os.chmod(dest, 0o600)
            ui.success(f"installed: {f.name}")
            installed += 1

    ui.console.print()
    if installed > 0:
        word = "policy" if installed == 1 else "policies"
        ui.success(f"Installed {installed} baseline {word}.")
    if skipped > 0:
        ui.dim(f"Skipped {skipped} (already present). Delete to reinstall.")
    ui.console.print()
    ui.info(f"Policies active at: {_cfg.POLICIES_DIR}")
    ui.info('Test: docket policies test pre_tool_call programmer "rm -rf /tmp"')
    return 0


def _test(args: list[str]) -> int:
    hook = args[0] if len(args) > 0 else ""
    role = args[1] if len(args) > 1 else ""
    text = args[2] if len(args) > 2 else ""
    if not hook or not role or not text:
        ui.error('Usage: docket policies test <hook> <role> "<text>"')
        return 1
    if hook not in _VALID_HOOKS:
        ui.error(f"Unknown hook '{hook}'. Valid: {' '.join(_VALID_HOOKS)}")
        return 1

    ui.info("Evaluating policies (dry-run, no traces emitted)...")
    action = _policy.policy_test(hook, role, text)

    ui.console.print()
    ui.console.print(f"  Hook:   {hook}")
    ui.console.print(f"  Role:   {role}")
    ui.console.print(f"  Text:   {text[:80]}")
    ui.console.print()

    colour = {
        "allow": "green",
        "warn": "yellow",
        "redact": "yellow",
        "require_approval": "cyan",
        "block": "red",
    }.get(action)
    if colour:
        ui.console.print(f"  Result: [{colour}]{action}[/{colour}]")
    else:
        ui.console.print(f"  Result: {action}")
    ui.console.print()
    return 0


def run_policies(sub: str | None = None, *, args: list[str] | None = None) -> int:
    """Dispatch the policies subcommand. Returns the process exit code.

    sub:  list (default) | show | init | test | -h/--help
    args: trailing positional args for show/test.
    """
    rest = args or []
    subcmd = sub or "list"
    if subcmd == "list":
        return _list()
    if subcmd == "show":
        return _show(rest)
    if subcmd == "init":
        return _init()
    if subcmd == "test":
        return _test(rest)
    return _help()
