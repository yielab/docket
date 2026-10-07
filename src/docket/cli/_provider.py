"""docket models provider -- register, list, show, remove and export a provider document.

`core/provider.py` does the pure verify -> classify -> register orchestration and returns a
`Registration`/`ProviderVerification`; this module renders those results and the next-steps
guidance, keeping presentation-layer output out of `core` ("core has no knowledge of terminals").
"""

from __future__ import annotations

import json as _json
from pathlib import Path

from pydantic import ValidationError

from docket import ui
from docket.core import models_policy as _mp
from docket.core import provider as _prov

# The bare `add` shortcut's ctx/max-tokens: no home in the `local` built-in document (it carries
# no `models[]` row), so these two literals -- matching the pre-catalog defaults -- fill the gap
# only when neither flag is given.
_SHORTCUT_CTX = 16384
_SHORTCUT_MAX_TOKENS = 8192


def run_provider(action: str, args: list[str]) -> int:
    """Dispatch one `docket models provider <action> ...` call. Returns a process exit code."""
    handlers = {
        "add": _run_add,
        "list": _run_list,
        "show": _run_show,
        "remove": _run_remove,
        "export": _run_export,
    }
    handler = handlers.get(action)
    if handler is None:
        ui.error(
            f"Unknown provider action '{action}'.\n"
            "Usage:\n"
            "  docket models provider add <file.yaml>\n"
            "  docket models provider add <name> <base-url> [--model ID] [--ctx N]"
            " [--max-tokens N] [--credential NAME]\n"
            "  docket models provider list\n"
            "  docket models provider show <name> [--json]\n"
            "  docket models provider remove <name>\n"
            "  docket models provider export <name> [<file>]"
        )
        return 1
    return handler(args)


def _parse_opts(args: list[str]) -> tuple[list[str], dict[str, str]]:
    """Split *args* into positionals and `--key value`/`--key=value` options -- the same shape
    every hand-parsed docket subcommand (e.g. the pre-catalog `provider add`) has used."""
    pos: list[str] = []
    opts: dict[str, str] = {}
    i = 0
    while i < len(args):
        tok = args[i]
        if tok.startswith("--"):
            key = tok[2:]
            if "=" in key:
                k, v = key.split("=", 1)
                opts[k] = v
            else:
                opts[key] = args[i + 1] if i + 1 < len(args) else ""
                i += 1
        else:
            pos.append(tok)
        i += 1
    return pos, opts


def _build_shortcut_spec(pos: list[str], opts: dict[str, str]) -> _prov.ProviderSpec:
    """Build the document a `docket models provider add <name> <base-url> [--opts]` call (or
    the bare, no-argument shortcut) produces -- today's shortcut, kept, over the new document
    shape. A bare `add` takes its name and base URL from the built-in `local` document."""
    local_builtin = _prov.load_catalog().get("local")
    default_base_url = local_builtin.base_url if local_builtin else "http://127.0.0.1:8080/v1"
    default_model_id = ""
    if local_builtin is not None:
        local_preset = next((p for p in local_builtin.presets if p.name == "local"), None)
        if local_preset is not None:
            default_model_id = local_preset.ranks.get("standard", "")

    name = pos[0] if len(pos) > 0 else "local"
    base_url = pos[1] if len(pos) > 1 else default_base_url
    model_id = opts.get("model", default_model_id or "local-model")
    ctx = int(opts.get("ctx") or _SHORTCUT_CTX)
    max_tokens = int(opts.get("max-tokens") or _SHORTCUT_MAX_TOKENS)
    credential = opts.get("credential", "")
    auth = (
        _prov.AuthSpec(type="bearer", credentials=[credential])
        if credential
        else _prov.AuthSpec(type="none")
    )

    return _prov.ProviderSpec(
        name=name,
        dialect="openai-chat",
        base_url=base_url,
        auth=auth,
        local=not credential,
        models=[_prov.ModelRow(id=model_id, contextWindow=ctx, maxTokens=max_tokens)],
    )


def _run_add(args: list[str]) -> int:
    pos, opts = _parse_opts(args)

    if len(pos) == 1 and Path(pos[0]).is_file():
        try:
            spec = _prov.load_provider_document(pos[0])
        except _prov.ProviderError as exc:
            ui.error(str(exc))
            return 1
    elif len(pos) == 1 and not Path(pos[0]).is_file():
        ui.error(f"'{pos[0]}' is neither an existing file nor '<name> <base-url>'.")
        return 1
    else:
        try:
            spec = _build_shortcut_spec(pos, opts)
        except ValidationError as exc:
            ui.error(f"invalid provider: {exc}")
            return 1

    ui.info(f"Checking the endpoint is alive: {spec.base_url}/models")
    reg = _prov.register_provider(spec)
    verification = reg.verification

    if not verification.reachable:
        ui.error(
            f"Could not reach {spec.base_url}/models"
            + (f": {verification.warning}" if verification.warning else "")
            + ". Provider was not registered; start the OpenAI-compatible server (or check the"
            " URL) and retry the same command."
        )
        return 1

    ui.info(f"Registering provider '{spec.name}'")
    if reg.changed:
        ui.success(f"Provider wired: {spec.name}  ->  {spec.base_url}")
    else:
        ui.success(f"Provider already wired: {spec.name}  ->  {spec.base_url} (no change)")

    if verification.warning:
        ui.warn(verification.warning)
    if verification.credential_name and not verification.credential_present:
        ui.console.print(f"  Store it: docket keys add {verification.credential_name}")

    if spec.auth.type == "none":
        model_id = spec.models[0].id if spec.models else ""
        _print_local_selection(spec.name, model_id)
    return 0


def _run_list(_args: list[str]) -> int:
    catalog = _prov.load_catalog()
    if not catalog.entries:
        ui.console.print("No providers registered.")
        return 0

    ui.header("Providers")
    ui.console.print()
    fmt = "  {:<16}  {:<9}  {:<12}  {:<40}  {}"
    ui.console.print(
        f"[bold]{fmt.format('NAME', 'SCOPE', 'DIALECT', 'BASE URL', 'CREDENTIAL')}[/bold]"
    )
    for name in sorted(catalog.entries):
        spec = catalog.entries[name]
        credential = ", ".join(spec.auth.credentials) or "-"
        ui.console.print(
            fmt.format(name, catalog.source_of(name), spec.dialect, spec.base_url, credential)
        )
    return 0


def _run_show(args: list[str]) -> int:
    pos, opts = _parse_opts(args)
    if not pos:
        ui.error("Usage: docket models provider show <name> [--json]")
        return 1

    name = pos[0]
    catalog = _prov.load_catalog()
    spec = catalog.get(name)
    if spec is None:
        ui.error(f"Unknown provider '{name}'.")
        return 1
    scope = catalog.source_of(name)

    if "json" in opts:
        payload = {"scope": scope, **spec.model_dump(by_alias=True)}
        ui.console.print(_json.dumps(payload, indent=2))
        return 0

    ui.header(f"Provider: {name} ({scope})")
    ui.console.print()
    ui.console.print(f"  dialect       {spec.dialect}")
    ui.console.print(f"  base URL      {spec.base_url}")
    ui.console.print(
        f"  auth          {spec.auth.type}"
        + (f" ({', '.join(spec.auth.credentials)})" if spec.auth.credentials else "")
    )
    ui.console.print(f"  local         {spec.local}")
    if spec.models:
        ui.console.print("  models        " + ", ".join(row.id for row in spec.models))
    return 0


def _run_remove(args: list[str]) -> int:
    pos, _opts = _parse_opts(args)
    if not pos:
        ui.error("Usage: docket models provider remove <name>")
        return 1
    try:
        _prov.remove_provider(pos[0])
    except _prov.ProviderError as exc:
        ui.error(str(exc))
        return 1
    ui.success(f"Removed provider '{pos[0]}'.")
    return 0


def _run_export(args: list[str]) -> int:
    pos, _opts = _parse_opts(args)
    if not pos:
        ui.error("Usage: docket models provider export <name> [<file>]")
        return 1
    try:
        text = _prov.export_provider(pos[0])
    except _prov.ProviderError as exc:
        ui.error(str(exc))
        return 1
    if len(pos) > 1:
        Path(pos[1]).write_text(text, encoding="utf-8")
        ui.success(f"Exported '{pos[0]}' to {pos[1]}")
    else:
        ui.console.print(text, end="")
    return 0


def _print_local_selection(name: str, model_id: str) -> None:
    """Print a keyless all-local selection path without implying a vendor subscription."""
    ui.console.print()
    ui.console.print("Next — select the reachable local provider:")
    ui.console.print()
    if name == "local":
        ui.console.print("  docket models preset local")
        ui.console.print(f"    # selects the registered model: {name}/{model_id}")
    else:
        for role in _mp.ALL_ROLES:
            ui.console.print(f"  docket models set {role:<11} {name}/{model_id}")
    ui.console.print(
        "  docket models                                               "
        "# confirm the role→model table"
    )
    ui.console.print()
    ui.console.print("Then smoke-test the split:")
    ui.console.print()
    ui.console.print(
        '  docket pod <project> delegate "Write hello.py with a pytest test, then run it"'
    )
    ui.console.print(
        "  docket pod <project> dispatch                               "
        "# all roles use the selected local endpoint"
    )
