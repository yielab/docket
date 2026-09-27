"""docket recipes — list and inspect the recipe library (operator + shipped).

  docket recipes list [--json]              Every recipe reachable by name, nearest-scope wins.
  docket recipes show <name|dir> [--json]   One recipe's description, scope, directory, and
                                             derived summary; the README body when present.

``run_recipes(args)`` returns the process exit code. Wires ``core.pod_apply.list_recipes``/
``resolve_recipe``/``summarize_recipe`` -- the same read-only views ``docket validate`` and
``docket pod <p> apply --dry-run`` already print, gathered into one discovery surface
(ADR 0013 SS1 rule 5). Installs, removes, or fetches nothing; ``docket pod <p> apply``/
``docket init --recipe`` remain the only writers."""

from __future__ import annotations

import json as _json

from rich.markup import escape

from docket import ui
from docket.cli._flags import find_unknown_flag
from docket.core import pod_apply as _pod_apply


def _kind_of(summary: _pod_apply.RecipeSummary) -> str:
    """Derive a one-word kind from what the recipe brings -- never a declared field
    (ADR 0013 SS1 rule 1)."""
    has_pipeline = bool(summary.pipeline)
    has_policies = summary.policies > 0
    has_members = summary.members > 0
    if has_members and has_pipeline:
        return "team"
    if has_policies and not has_pipeline and not has_members:
        return "policies"
    if has_pipeline and not has_policies:
        return "pipeline"
    return "mixed"


def _info_dict(
    name: str, scope: str, directory: str, summary: _pod_apply.RecipeSummary
) -> dict[str, object]:
    return {
        "name": name,
        "scope": scope,
        "kind": _kind_of(summary),
        "directory": directory,
        "description": summary.description,
        "roles": summary.roles,
        "policies": summary.policies,
        "members": summary.members,
        "pipeline": summary.pipeline,
        "plugins": summary.plugins,
        "skills": summary.skills,
        "settings": summary.settings,
    }


def _list(json_out: bool) -> int:
    infos = _pod_apply.list_recipes()
    if json_out:
        print(
            _json.dumps(
                [_info_dict(i.name, i.scope, str(i.directory), i.summary) for i in infos],
                indent=2,
            )
        )
        return 0
    ui.header("Recipe Library")
    ui.console.print()
    print(f"  {'NAME':<20} {'SCOPE':<10} {'KIND':<10} DESCRIPTION")
    print(f"  {'-' * 90}")
    for info in infos:
        print(
            f"  {info.name:<20} {info.scope:<10} {_kind_of(info.summary):<10} "
            f"{info.summary.description}"
        )
    ui.console.print()
    return 0


def _show(name_or_dir: str, json_out: bool) -> int:
    try:
        directory = _pod_apply.resolve_recipe(name_or_dir)
    except _pod_apply.PodApplyError as exc:
        ui.error(str(exc))
        return 1
    summary = _pod_apply.summarize_recipe(directory)
    scope = next(
        (info.scope for info in _pod_apply.list_recipes() if info.directory == directory), ""
    )
    readme = directory / "README.md"
    readme_body = readme.read_text(encoding="utf-8") if readme.is_file() else ""

    if json_out:
        payload = _info_dict(directory.name, scope, str(directory), summary)
        payload["readme"] = readme_body
        print(_json.dumps(payload, indent=2))
        return 0

    ui.header(directory.name)
    if summary.description:
        ui.console.print(escape(summary.description))
    if scope:
        ui.console.print(f"  scope: {scope}")
    ui.console.print(f"  directory: {directory}")
    ui.console.print(f"  {escape(summary.render())}")
    if readme_body:
        ui.console.print()
        ui.console.print(escape(readme_body))
    return 0


def run_recipes(args: list[str] | None = None) -> int:
    """Dispatch the recipes subcommand (``list``, the default; or ``show <name|dir>``) and
    return the exit code. An unknown recipe name exits 1 with the resolution error."""
    rest = list(args or [])
    sub = "list"
    if rest and not rest[0].startswith("-"):
        sub = rest[0]
        rest = rest[1:]

    bad = find_unknown_flag(rest, frozenset({"--json"}))
    if bad is not None:
        ui.error(f"docket recipes: unrecognized flag '{bad}'")
        return 2

    json_out = "--json" in rest
    positional = [a for a in rest if a != "--json"]

    if sub == "list":
        if positional:
            ui.error("Usage: docket recipes list [--json]")
            return 1
        return _list(json_out)
    if sub == "show":
        if len(positional) != 1:
            ui.error("Usage: docket recipes show <name|dir> [--json]")
            return 1
        return _show(positional[0], json_out)

    ui.error("Usage: docket recipes <list|show> [args]")
    return 1
