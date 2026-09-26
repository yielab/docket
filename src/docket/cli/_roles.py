"""docket roles — inspect and manage declarative role archetypes.

  docket roles list [--pod <p>]                 List every registered archetype
                                                 (built-in, starter library, user-
                                                 defined, and <p>'s own overlay)
  docket roles show <name> [--pod <p>]          Show one archetype's full definition
  docket roles add <file.yaml> [--pod <p>]      Validate a YAML archetype definition
                                                 and merge it into the user overlay,
                                                 or pod <p>'s own overlay
  docket roles validate [file.yaml]             Validate the live registry, or a
                                                 candidate file without persisting it

``run_roles(sub, args)`` returns the process exit code. The registry itself
(built-ins + starter library + global user overlay + a pod's own overlay) lives in
`core/archetypes.py`; this module is the presentation layer only — it never touches
`~/.docket/docket-roles.json` or a pod's `roles.json` directly (that's
`core/archetypes.py`'s `add_user_archetype`, which goes through `edges/store.py`).
`--pod <p>` (list/show/add only) resolves and, for `add`, writes against pod `<p>`'s
own overlay, which `core/archetypes.py::load_registry` resolves nearest-wins above
the global overlay -- `docket roles validate` has no pod-specific overlay concept,
so it does not take the flag.
"""

from __future__ import annotations

import docket.config as _cfg
from docket import ui
from docket.cli._flags import find_unknown_flag
from docket.core import archetypes as _arch

_DOCUMENTED_FLAGS: frozenset[str] = frozenset({"--pod"})


def _parse_pod_flag(args: list[str]) -> tuple[str, list[str]]:
    """Extract `--pod <p>`/`--pod=<p>` from *args*, returning ``(pod, remaining)``."""
    pod = ""
    rest: list[str] = []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--pod" and i + 1 < len(args):
            pod = args[i + 1]
            i += 2
            continue
        if tok.startswith("--pod="):
            pod = tok[len("--pod=") :]
            i += 1
            continue
        rest.append(tok)
        i += 1
    return pod, rest


def _help() -> int:
    ui.header("docket roles")
    ui.console.print()
    ui.console.print("  docket roles list [--pod <p>]              List every registered archetype")
    ui.console.print(
        "  docket roles show <name> [--pod <p>]       Show one archetype's full definition"
    )
    ui.console.print(
        "  docket roles add <file.yaml> [--pod <p>]   Add/override an archetype from a YAML file"
    )
    ui.console.print(
        "  docket roles validate [file.yaml]          Validate the registry, or a candidate file"
    )
    ui.console.print()
    ui.console.print("  --pod <p>: resolve/write against pod <p>'s own overlay (nearest-wins)")
    ui.console.print("  Scopes: org | pod   Model classes: cheap | strong")
    ui.console.print("  Gate contracts: none | verdict | mechanical | approval")
    ui.console.print("  Edit rights: none | read-only | write")
    ui.console.print()
    ui.console.print(f"  User overlay: {_cfg.ARCHETYPE_REGISTRY_FILE}")
    ui.console.print()
    return 0


def _list(pod: str = "") -> int:
    ui.header("Role Archetypes")
    ui.console.print()

    registry = _arch.load_registry(pod)
    if not registry.role_names():
        ui.warn("No archetypes registered.")
        return 0

    # Data rows use plain print() so archetype names/prose are never parsed as
    # Rich markup (matches cli/_policies.py's convention for the same reason).
    print(
        f"  {'NAME':<14} {'SOURCE':<10} {'SCOPE':<5} {'CLASS':<7} {'GATE':<11} {'EDIT':<10} DESCRIPTION"
    )
    print(f"  {'─' * 100}")
    for name, arch in registry.items():
        source = registry.source_of(name)
        print(
            f"  {name:<14} {source:<10} {arch.scope:<5} {arch.model_class:<7} "
            f"{arch.gate_contract.kind:<11} {arch.edit_rights:<10} {arch.description[:40]}"
        )
    ui.console.print()
    ui.dim(f"  Built-in: {', '.join(_arch.BUILTIN_ROLE_ORDER)}")
    ui.dim(f"  Starter library: {', '.join(_arch.STARTER_ROLE_ORDER)}")
    ui.console.print()
    return 0


def _show(args: list[str], pod: str = "") -> int:
    if not args or not args[0]:
        ui.error("Usage: docket roles show <name> [--pod <p>]")
        return 1
    name = args[0]
    registry = _arch.load_registry(pod)
    found = registry.get(name)
    if found is None:
        ui.fail(f"Archetype not found: {name}")
        return 1

    try:
        import yaml as _yaml  # type: ignore[import-untyped]

        text = _yaml.safe_dump(found.to_wire(), sort_keys=False, allow_unicode=True)
    except ImportError:
        import json as _json

        text = _json.dumps(found.to_wire(), indent=2)

    ui.console.print()
    ui.console.print(f"  [bold]{name}[/bold]  (source: {registry.source_of(name)})")
    ui.console.print()
    print(text)
    return 0


def _add(args: list[str], pod: str = "") -> int:
    if not args or not args[0]:
        ui.error("Usage: docket roles add <file.yaml> [--pod <p>]")
        return 1
    path = args[0]
    try:
        doc = _arch.load_role_file(path)
        arch = _arch.add_user_archetype(doc, pod)
    except _arch.ArchetypeError as exc:
        ui.fail(f"Invalid archetype: {exc}")
        return 1

    ui.success(
        f"Added archetype '{arch.name}' (scope={arch.scope}, modelClass={arch.model_class})."
    )
    dest = _cfg.pod_config_dir(pod) / "roles.json" if pod else _cfg.ARCHETYPE_REGISTRY_FILE
    ui.info(f"Registered at: {dest}")
    return 0


def _validate(args: list[str]) -> int:
    if args and args[0]:
        try:
            doc = _arch.load_role_file(args[0])
        except _arch.ArchetypeError as exc:
            ui.fail(f"Invalid archetype file: {exc}")
            return 1
        name = str(doc.get("name", "")).strip()
        if not name:
            ui.fail("Archetype definition must have a top-level 'name'.")
            return 1
        errors = _arch.validate_archetype_dict(name, doc)
        if errors:
            ui.fail(f"'{name}' is invalid:")
            for err in errors:
                ui.console.print(f"  - {err}")
            return 1
        ui.success(f"'{name}' is valid.")
        return 0

    # No file: validate the whole live registry (built-ins + starter + user overlay).
    registry = _arch.load_registry()
    all_ok = True
    for name, found in registry.items():
        errors = _arch.validate_archetype_dict(name, found.to_wire())
        if errors:
            all_ok = False
            ui.fail(f"'{name}' is invalid:")
            for err in errors:
                ui.console.print(f"  - {err}")
        else:
            ui.success(f"'{name}' is valid.")
    return 0 if all_ok else 1


def run_roles(sub: str | None = None, *, args: list[str] | None = None) -> int:
    """Dispatch the roles subcommand. Returns the process exit code.

    sub:  list (default) | show | add | validate | -h/--help
    args: trailing positional args for show/add/validate.
    """
    rest = args or []
    bad = find_unknown_flag(rest, _DOCUMENTED_FLAGS)
    if bad is not None:
        ui.error(f"docket roles: unrecognized flag '{bad}'")
        return 2
    subcmd = sub or "list"
    pod, rest = _parse_pod_flag(rest)
    if subcmd == "list":
        return _list(pod)
    if subcmd == "show":
        return _show(rest, pod)
    if subcmd == "add":
        return _add(rest, pod)
    if subcmd == "validate":
        return _validate(rest)
    return _help()
