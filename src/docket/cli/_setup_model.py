"""The model setup commands.
Holds models and keys."""

from __future__ import annotations

import contextlib

import typer
from rich.markup import escape

import docket.config as _cfg
from docket import ui
from docket.core import models_policy as _mp
from docket.core.audit import audit_log


def cmd_keys(
    ctx: typer.Context,
    sub: str | None = typer.Argument(None),
) -> None:
    """API key management (add/list/remove/rotate/validate/export/setup).

    Docket's model client reads keys centrally.

    Subcommands:
      list (default)     masked table of stored keys with a format badge and
                          the date added
      add <KEY_NAME>      name must be UPPERCASE_WITH_UNDERSCORES (e.g.
                           ANTHROPIC_API_KEY); prompts for the hidden value
                           via getpass; errors (exit 1) if the name already
                           exists -- use rotate instead
      remove <KEY_NAME>    deletes a stored key, confirming interactively if
                            stdin is a TTY
      rotate <KEY_NAME>    replaces the value of an existing key (errors,
                            exit 1, if it doesn't already exist)
      validate [KEY_NAME]  checks stored key(s) against known provider
                            prefix/length rules (e.g. ANTHROPIC_API_KEY must
                            start `sk-ant-` and be >= 40 chars); no name
                            validates everything; exit 1 on any failure
      export               prints `export NAME='value'` lines (unmasked,
                            shell-quoted) for every stored key, for
                            `eval "$(docket keys export)"`
      setup                interactive wizard (requires a TTY) through
                            every credential the provider catalog declares,
                            in catalog order, one at a time

    Stored in `~/.docket/secrets.json` (values, 0600) and
    `secrets.meta.json` (added/rotated timestamps) -- docket-owned JSON,
    written through `edges/store.py`. Recognized provider keys:
    ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_AI_API_KEY, OPENROUTER_API_KEY,
    AI_GATEWAY_API_KEY, VERCEL_OIDC_TOKEN, GROQ_API_KEY, MISTRAL_API_KEY,
    XAI_API_KEY, CEREBRAS_API_KEY, HUGGINGFACE_TOKEN. The runtime reads a
    selected provider's stored credential directly -- exporting is optional.
    Under DOCKET_SECRETS_BACKEND=keyring, add/rotate store the value in the
    OS keyring (secret-tool) instead of secrets.json, which then keeps only
    a name index; remove clears the keyring entry too."""
    from docket.cli._keys import run_keys

    raise typer.Exit(run_keys(sub, list(ctx.args)))


def cmd_models(ctx: typer.Context) -> None:
    """View and edit the role->model policy -- the single place that decides
    which model each kind of agent runs on.

    Roles are the archetype names. Built-in defaults put high-volume/low-reasoning
    roles (lead, reviewer, tester, monitor, analyst, writer) on the cheap model
    class and reasoning-dense roles (implementer, critic, operator, researcher)
    on the strong class.

    Subcommands: (bare) show the role->model policy with pricing and why;
    `set <role> <provider/model>` change one role's model, or
    `set default <provider/model>` the fallback; `preset [name]` list or
    apply a provider preset from the catalog (anthropic (default), openai,
    google, openrouter-free (experimental zero-cost router), openrouter,
    ai-gateway (Vercel), local (no API key, priced at $0 (local)) among
    others) -- a built-in hosted preset needs only its credential, never a
    separate registration; `reset` restore built-in defaults (asks for
    confirmation); `provider <action>` manage the provider catalog: `add
    <file.yaml>` a `kind: provider` document, or the shortcut `add <name>
    <base-url> [--model ID] [--ctx N] [--max-tokens N] [--credential NAME]`
    (registration verifies `<base-url>/models` with the resolved credential
    and classifies the result -- only a transport failure refuses; every
    HTTP status registers, with a warning when it is not a clean 200);
    `list` every provider (name, scope, dialect, base URL, credential);
    `show <name> [--json]` one entry; `remove <name>` a global override
    (a built-in with none refuses); `export <name> [<file>]` its document.

    Policy changes are live: every policy-following agent is re-resolved
    immediately; pinned agents (`docket profile <id> <model>`) are never
    touched. Overrides persist in `~/.docket/docket-models.json` (`roles:`
    map); delete it or run `reset` to restore built-ins -- `reset` prompts
    `Continue? [y/N]` and a non-interactive call that can't answer aborts
    rather than silently resetting the fleet. Applying a preset also writes
    its own economy/standard/premium anchors, re-resolves every
    policy-following agent, and prints a readiness line naming the preset's
    credential as present or missing. Unknown models are accepted if
    well-formed (`provider/model`) -- an id absent from the catalog only
    surfaces the first time an agent actually calls the endpoint; pricing
    shows n/a (or "n/a (bring your own)" for an OpenRouter/AI Gateway route
    other than the explicit free router, and "$0 (local)" for a
    local/ollama/lmstudio provider -- never a fabricated dollar figure).
    An invalid model prints the current role policy table alongside the
    error."""
    args = ctx.args
    sub = args[0] if args else "list"
    rest = args[1:]

    if sub in ("list", ""):
        _cmd_models_list()
    elif sub == "set":
        if len(rest) < 2:
            ui.error("Usage: docket models set <role|default> <provider/model>")
            raise typer.Exit(1)
        _cmd_models_set(rest[0], rest[1])
    elif sub == "preset":
        _cmd_models_preset(rest[0] if rest else None)
    elif sub == "reset":
        _cmd_models_reset()
    elif sub == "provider":
        if not rest:
            ui.error("Usage: docket models provider <add|list|show|remove|export> ...")
            raise typer.Exit(1)
        from docket.cli import _provider

        raise typer.Exit(_provider.run_provider(rest[0], rest[1:]))
    else:
        ui.error(
            f"Unknown models subcommand '{sub}'.\n"
            "Usage:\n"
            "  docket models                            # show role→model policy\n"
            "  docket models set <role> <model>         # change a role's model\n"
            "  docket models preset [name]              # list or apply a provider preset\n"
            "  docket models reset                      # restore built-in defaults\n"
            "  docket models provider add <name> <url>  # register a provider"
        )
        raise typer.Exit(1)


def _cmd_models_list() -> None:
    role_models, tiers, default_model = _mp.load_registry()
    reg_exists = _cfg.MODEL_REGISTRY_FILE.exists()

    ui.header("Role→model policy")
    ui.console.print()
    fmt = "  {:<12}  {:<38}  {:<14}  {:<8}  {}"
    ui.console.print(f"[bold]{fmt.format('ROLE', 'MODEL', 'PRICE', 'SOURCE', 'WHY')}[/bold]")
    ui.console.print(fmt.format("----", "-----", "-----", "------", "---"))

    models_shown: list[str] = []
    for role in _mp.ALL_ROLES:
        m = role_models.get(role, _cfg.DEFAULT_MODEL)
        models_shown.append(m)
        price = _mp.pricing_label(m)
        # source: 'user' if the registry has an explicit role override, else 'builtin'
        reg_roles: dict[str, str] = {}
        if reg_exists:
            try:
                import json as _j

                reg_roles = _j.loads(_cfg.MODEL_REGISTRY_FILE.read_text(encoding="utf-8")).get(
                    "roles", {}
                )
            except Exception:
                pass
        source = "user" if role in reg_roles and reg_roles[role] == m else "builtin"
        why = _mp.role_why(role)
        ui.console.print(fmt.format(role, m, price, source, why))

    ui.console.print()
    ui.console.print(f"  {'default':<12}  {default_model}")
    ui.console.print(
        f"  {'rank anchors':<12}  "
        f"{tiers.get('premium', '')} → {tiers.get('standard', '')} → {tiers.get('economy', '')}"
    )
    ui.dim(
        "  (role-default seed table — not a runtime fallback chain; overridable in docket-models.json)"
    )
    ui.console.print()
    ui.console.print(f"  Registry file: {_cfg.MODEL_REGISTRY_FILE}")
    if reg_exists:
        ui.console.print("  (user overrides active)")
    else:
        ui.console.print("  (no user overrides — using built-in defaults)")
    snapshot_dates = {d for m in models_shown if (d := _mp.prices_as_of(m))}
    if snapshot_dates:
        snapshot = next(iter(snapshot_dates)) if len(snapshot_dates) == 1 else "various"
        ui.dim(f"  PRICE column is an estimate from a snapshot (as of {snapshot})")
    ui.console.print()
    ui.console.print("Change: docket models set <role|default> <provider/model>")
    # markup=False: the literal [anthropic|...] must not be parsed as Rich
    # markup. Derived from known_presets() so a new preset can't silently go
    # missing from this line the way `local` once did.
    ui.console.print(
        f"Preset: docket models preset [{'|'.join(_mp.known_presets())}]",
        markup=False,
    )
    ui.console.print(
        "Pin one agent instead: docket profile <id> <provider/model>"
        "   (back: docket profile <id> default)"
    )


def _cmd_models_set(key: str, model: str) -> None:
    try:
        validated, warnings = _mp.validate_model(model)
    except ValueError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from None
    for w in warnings:
        ui.warn(w)

    role_models, _tiers, default_model = _mp.load_registry()
    updates: dict[str, str] = {}
    touched_roles: list[str] = []

    if key == "default":
        before = default_model
        updates["default"] = validated
    elif _mp.is_role(key):
        before = role_models.get(key, _cfg.DEFAULT_MODEL)
        updates[f"role.{key}"] = validated
        touched_roles.append(key)
    else:
        all_r = " ".join(_mp.ALL_ROLES)
        ui.error(f"Unknown key '{key}'. Use a role ({all_r}) or 'default'.")
        raise typer.Exit(1)

    _mp.write_registry(updates)
    audit_log("models.set", f"role={key} {before}->{validated}")
    ui.success(f"{key} → {validated}")
    price = _mp.pricing_label(validated)
    if price.startswith("n/a"):
        ui.info(f"No pricing data for {validated} — cost will show as {price}.")

    if touched_roles:
        ui.console.print()
        ui.info("Re-resolving policy-following agents...")
        n = _mp.reapply_role_policy()
        if n:
            ui.console.print(f"  {n} agent(s) updated.")


def _cmd_models_preset(preset: str | None) -> None:
    table = _mp.preset_table()
    if preset is None:
        ui.header("Provider presets")
        ui.console.print()
        fmt = "  {:<18}  {:<8}  {:<20}  {}"
        ui.console.print(
            f"[bold]{fmt.format('PRESET', 'COST', 'KEY NEEDED', 'DESCRIPTION')}[/bold]"
        )
        ui.console.print(fmt.format("------", "----", "----------", "-----------"))
        for p in _mp.known_presets():
            t = table[p]
            marker = " (default)" if p == "anthropic" else ""
            ui.console.print(escape(fmt.format(f"{p}{marker}", t["cost"], t["key"], t["note"])))
        ui.console.print()
        ui.console.print("Apply: docket models preset <name>")
        ui.console.print()
        ui.console.print(
            "Free options: openrouter-free (experimental zero-cost router at openrouter.ai)"
            " · local (no API key, run your own OpenAI-compatible endpoint)"
        )
        return

    if preset not in table:
        valid = " ".join(_mp.known_presets())
        ui.error(f"Unknown preset '{preset}'. Valid: {valid}")
        raise typer.Exit(1)

    # Every preset name in `table` is attached to a catalog entry (built-in or global) by
    # construction (see `models_policy.presets()`), so `registered` is never None here -- a
    # direct anthropic/openai/google preset needs no separate "is it registered" gate any more:
    # the built-in document itself is the registration. `local`'s own resolved entry is still
    # read below, for its exact selected-model-id special case.
    from docket.core import provider as _prov

    registered = _prov.load_catalog().get(preset)

    t = table[preset]
    econ, std, prem = t["economy"], t["standard"], t["premium"]
    if preset == "local" and registered is not None and registered.models:
        registered_id = registered.models[0].id.strip()
        if registered_id:
            econ = std = prem = f"local/{registered_id}"
    cost, note = t["cost"], t["note"]

    before_roles, _before_tiers, before_default = _mp.load_registry()

    cheap_roles = [r for r in _mp.ALL_ROLES if _mp.ROLE_CLASS.get(r) == "cheap"]
    strong_roles = [r for r in _mp.ALL_ROLES if _mp.ROLE_CLASS.get(r) == "strong"]

    updates: dict[str, str] = {
        "default": std,
        # Persist the preset's own economy/standard/premium as the rank
        # anchors too — otherwise a non-Anthropic preset still
        # left Claude ids in the "rank anchors" line `docket models` prints.
        "rank.economy": econ,
        "rank.standard": std,
        "rank.premium": prem,
    }
    for r in cheap_roles:
        updates[f"role.{r}"] = econ
    for r in strong_roles:
        updates[f"role.{r}"] = std

    ui.console.print()
    ui.info(f"Applying preset: {preset}")
    ui.console.print(f"  {' '.join(cheap_roles)}")
    ui.console.print(f"    → {econ}")
    ui.console.print(f"  {' '.join(strong_roles)}")
    ui.console.print(f"    → {std}")
    ui.console.print(f"  rank anchor (seed only, not a fallback) → {prem}")
    if cost == "free":
        ui.console.print("  cost → free per-token (zero cost on free-tier models)")
    else:
        ui.console.print("  cost → paid")
    if note:
        ui.console.print(escape(f"  note → {note}"))
    ui.console.print()

    _mp.write_registry(updates)

    # One entry for the whole preset application (matching agent.add's
    # whole-pod-in-one-line style), not one per role: role_after maps every
    # role to the model the preset just assigned it (econ for cheap-class,
    # std for strong-class — cheap_roles union strong_roles == ALL_ROLES).
    role_after: dict[str, str] = dict.fromkeys(cheap_roles, econ)
    role_after.update(dict.fromkeys(strong_roles, std))
    role_changes = ",".join(
        f"{r}:{before_roles.get(r, _cfg.DEFAULT_MODEL)}->{role_after[r]}" for r in _mp.ALL_ROLES
    )
    audit_log(
        "models.preset",
        f"preset={preset} default:{before_default}->{std} roles:{role_changes}",
    )
    ui.success(f"Preset '{preset}' applied.")

    ui.console.print()
    ui.info("Re-resolving policy-following agents...")
    n = _mp.reapply_role_policy()
    if n:
        ui.console.print(f"  {n} agent(s) updated.")

    readiness = _prov.model_readiness(std)
    if readiness.credential_present or not readiness.credential_name:
        ui.console.print(f"  readiness → {std}: ready")
    else:
        ui.console.print(f"  readiness → {std}: {readiness.credential_name} missing")

    key_name = t.get("key", "")
    if key_name:
        from docket.core import secrets as _secrets

        key_present = key_name in _secrets.secrets_keys()
        if not key_present:
            ui.console.print()
            ui.warn(f"API key {key_name} is not stored yet.")
            ui.console.print(f"  Add it: docket keys add {key_name}")
            if preset in ("openrouter-free", "openrouter"):
                ui.console.print("  Get one: https://openrouter.ai/keys (free account available)")
    elif preset == "local":
        ui.console.print()
        ui.success("Registered local endpoint selected; no API key needed.")

    ui.console.print()
    ui.info("Pinned agents kept their model. Pin or unpin one agent:")
    ui.console.print("  docket profile <id> <provider/model>   # pin")
    ui.console.print("  docket profile <id> default            # follow the role policy again")


def _cmd_models_reset() -> None:
    if not _cfg.MODEL_REGISTRY_FILE.exists():
        ui.info("No user overrides found (already using built-in defaults).")
        return

    ui.console.print()
    ui.warn(
        "This will remove all user model overrides and restore the built-in role policy"
        " (Anthropic defaults)."
    )
    ui.console.print()
    confirm = input("Continue? [y/N] ").strip()
    if confirm.lower() not in ("y", "yes"):
        ui.info("Aborted.")
        return

    before_roles, _before_tiers, before_default = _mp.load_registry()

    _mp.write_registry({}, reset=True)
    with contextlib.suppress(FileNotFoundError):
        _cfg.MODEL_REGISTRY_FILE.unlink()

    after_roles, _after_tiers, after_default = _mp.load_registry()
    role_changes = ",".join(
        f"{r}:{before_roles.get(r, _cfg.DEFAULT_MODEL)}->{after_roles.get(r, _cfg.DEFAULT_MODEL)}"
        for r in _mp.ALL_ROLES
    )
    audit_log("models.reset", f"default:{before_default}->{after_default} roles:{role_changes}")
    ui.success("Restored built-in model defaults.")

    ui.console.print()
    ui.info("Re-resolving policy-following agents...")
    n = _mp.reapply_role_policy()
    if n:
        ui.console.print(f"  {n} agent(s) updated.")
