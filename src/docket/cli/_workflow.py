"""docket workflow — manage Lobster YAML pipelines.

``run_workflow(aid, ws, sub, workflow_name)`` returns the process exit code;
the coordinator (``cli/__init__.py``) resolves/validates the agent id and
workspace (reusing its shared ``_pick_agent`` picker) and then wraps this in
a Typer command, raising ``typer.Exit(code)``.

Subcommands: list (default) | create <name> | show <name> | validate <name> |
plan/dry-run <name> | delete <name>. ``validate``/``plan`` wire into
``core/lobster.py`` (the deterministic-pipeline parser/planner); this module
owns only the CLI surface and the inline workflow template.
"""

from __future__ import annotations

import sys
from pathlib import Path

import docket.config as _cfg
from docket import ui
from docket.core.lobster import plan_lobster, validate_lobster
from docket.edges import store


def _resolve_workflow_file(wf_dir: Path, name: str) -> Path | None:
    """Return the workflow file for ``name``, trying both .yml and .yaml extensions."""
    for ext in (".lobster.yml", ".lobster.yaml"):
        p = wf_dir / f"{name}{ext}"
        if p.is_file():
            return p
    return None


def _workflow_template(name: str, agent_name: str, codebase: str, test_cmd: str) -> str:
    return f"""\
# Lobster Workflow: {name}
# Project: {agent_name}
#
# Deterministic pipeline — zero tokens for plumbing
# Only calls LLM for creative work

name: {name}
description: "Automated workflow for {agent_name}"

steps:
  - id: check-status
    type: shell
    command: |
      cd {codebase}
      git status --short

  - id: run-tests
    type: shell
    command: |
      cd {codebase}
      {test_cmd}
    continueOnError: false

  - id: llm-analysis
    type: llm
    prompt: |
      Analyze the test results and codebase state.
      Provide a brief summary and suggest next steps.
    approval: required
    # Pauses here and sends Telegram notification

  - id: apply-changes
    type: shell
    command: |
      cd {codebase}
      # Apply any changes suggested by LLM
      echo "Changes applied"

  - id: verify
    type: shell
    command: |
      cd {codebase}
      {test_cmd}

outputs:
  - testResults
  - analysis

notifications:
  onComplete: telegram
  onError: telegram
"""


def run_workflow(aid: str, ws: Path, sub: str | None, workflow_name: str | None) -> int:
    """Dispatch the workflow subcommand. Returns the process exit code."""
    action = sub or "list"
    wf_dir = ws / "workflows"

    try:
        raw = store.read_json(_cfg.meta_path(aid))
        agent_name = str(raw.get("name", aid))
    except Exception:
        agent_name = aid

    if action == "list":
        ui.header(f"Workflows: {agent_name}")
        ui.console.print()
        if not wf_dir.is_dir():
            ui.warn("No workflows directory")
            ui.console.print(f"  Create one: docket workflow {aid} create")
            return 0
        wfs = sorted(wf_dir.glob("*.lobster.y*ml"))
        if not wfs:
            ui.console.print("  No workflows defined yet")
            ui.console.print()
            ui.console.print("Create a workflow template:")
            ui.console.print(f"  docket workflow {aid} create <workflow-name>")
            return 0
        ui.console.print("[bold]Defined workflows:[/bold]")
        for wf in wfs:
            wf_name = wf.name
            for ext in (".lobster.yml", ".lobster.yaml"):
                wf_name = wf_name.replace(ext, "")
            try:
                steps = sum(
                    1 for ln in wf.read_text(encoding="utf-8").splitlines() if ln.startswith("  - ")
                )
            except OSError:
                steps = 0
            ui.console.print(f"  [green]●[/green] {wf_name:<24} {steps} steps")
        ui.console.print()
        ui.console.print(f"Run a workflow:  lobster run --workspace {ws} --workflow <name>")
        ui.console.print()
        return 0

    if action == "create":
        if not workflow_name:
            ui.error(f"Workflow name required.  Usage: docket workflow {aid} create <name>")
            return 1
        wf_dir.mkdir(parents=True, exist_ok=True)
        wf_file = wf_dir / f"{workflow_name}.lobster.yml"
        if wf_file.exists():
            ui.warn(f"Workflow '{workflow_name}' already exists")
            ui.console.print(f"  Edit: docket edit {aid}")
            return 0
        try:
            raw2 = store.read_json(_cfg.meta_path(aid))
        except Exception:
            raw2 = {}
        stack = str(raw2.get("stack", ""))
        codebase = str(raw2.get("codebase", ""))

        from docket.cli import _test_cmd_for_stack

        test_cmd = _test_cmd_for_stack(stack)
        template = _workflow_template(workflow_name, agent_name, codebase, test_cmd)
        wf_file.write_text(template, encoding="utf-8")
        wf_file.chmod(0o600)
        ui.success(f"Workflow created: {wf_file}")
        ui.console.print()
        ui.info("Next steps:")
        ui.console.print(f"  1. Edit workflow: $EDITOR {wf_file}")
        ui.console.print(
            f"  2. Run workflow:  lobster run --workspace {ws} --workflow {workflow_name}"
        )
        ui.console.print()
        return 0

    if action == "show":
        if not workflow_name:
            ui.error(f"Workflow name required.  Usage: docket workflow {aid} show <name>")
            return 1
        wf_file = wf_dir / f"{workflow_name}.lobster.yml"
        if not wf_file.is_file():
            ui.error(f"Workflow '{workflow_name}' not found")
            return 1
        ui.header(f"Workflow: {workflow_name}")
        ui.console.print()
        ui.console.print(wf_file.read_text(encoding="utf-8"))
        ui.console.print()
        return 0

    if action == "validate":
        if not workflow_name:
            ui.error(f"Workflow name required.  Usage: docket workflow {aid} validate <name>")
            return 1
        wf_path = _resolve_workflow_file(wf_dir, workflow_name)
        if wf_path is None:
            ui.error(f"Workflow '{workflow_name}' not found")
            return 1

        text = wf_path.read_text(encoding="utf-8")
        errors = validate_lobster(text)
        if errors:
            ui.error(f"Workflow '{workflow_name}' is invalid:")
            for e in errors:
                ui.console.print(f"  [red]✗[/red] {e}")
            return 1
        ui.success(f"Workflow '{workflow_name}' is valid")
        return 0

    if action in ("plan", "dry-run"):
        if not workflow_name:
            ui.error(f"Workflow name required.  Usage: docket workflow {aid} plan <name>")
            return 1
        wf_path = _resolve_workflow_file(wf_dir, workflow_name)
        if wf_path is None:
            ui.error(f"Workflow '{workflow_name}' not found")
            return 1

        text = wf_path.read_text(encoding="utf-8")
        plan, errors = plan_lobster(text, workflow_name)
        if errors:
            ui.error(f"Workflow '{workflow_name}' is invalid:")
            for e in errors:
                ui.console.print(f"  [red]✗[/red] {e}")
            return 1
        ui.console.print(plan)
        return 0

    if action == "delete":
        if not workflow_name:
            ui.error(f"Workflow name required.  Usage: docket workflow {aid} delete <name>")
            return 1
        wf_file = wf_dir / f"{workflow_name}.lobster.yml"
        if not wf_file.is_file():
            ui.error(f"Workflow '{workflow_name}' not found")
            return 1
        if sys.stdin.isatty():
            answer = input(f"Delete workflow '{workflow_name}'? [y/N]: ").strip().lower()
            if answer != "y":
                ui.warn("Aborted.")
                return 0
        wf_file.unlink()
        ui.success(f"Workflow '{workflow_name}' deleted")
        return 0

    ui.error(f"Unknown action '{action}'.  Use: list, create, show, validate, plan, or delete")
    return 1
