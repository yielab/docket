from __future__ import annotations

import shutil

from docket.governance import secrets as _secrets
from docket.interfaces.cli.render import ui
from docket.kernel import clock as _clock
from docket.kernel.home import current_home
from docket.models import catalog as _prov
from docket.models.catalog import ProviderSpec
from docket.platform import process as _process
from docket.platform import store
from docket.teams import fleet as _fleet


def _expected_credential(provider: str) -> str:
    """The provider's first credential name from the catalog, or ``""`` when *provider* is
    unknown or needs none -- the single reader both `_check_provider_coverage` and its JSON
    twin use, replacing the old hand-kept ``_PROVIDER_KEY`` table."""

    spec = _prov.load_catalog().get(provider)
    if spec is None or not spec.auth.credentials:
        return ""
    return spec.auth.credentials[0]


def _secrets_backend() -> str:
    """Resolve the secrets backend (keyring if requested + available, else file)."""
    if _process.secrets_backend_requested() == "keyring" and shutil.which("secret-tool"):
        return "keyring"
    return "file"


def _keys_age_report() -> list[tuple[str, str, str]]:
    """Return [(state, name, detail)] for each stored secret key; state is OK,
    STALE, or UNKNOWN."""
    keys = _secrets.secrets_keys()
    if not keys:
        return []
    meta = _secrets.load_secrets_meta()
    now = _clock.now()

    out: list[tuple[str, str, str]] = []
    for key in sorted(keys):
        entry = meta.get(key) or {}
        rotated = bool(entry.get("rotated_at"))
        ref = entry.get("rotated_at") or entry.get("added_at")
        dt = _clock.parse_iso(str(ref)) if ref else None
        if dt is None:
            out.append(("UNKNOWN", key, "age unknown (added before tracking)"))
            continue
        age = max(0, (now - dt).days)
        verb = "since rotation" if rotated else "old"
        state = "STALE" if age >= current_home().key_max_age_days else "OK"
        out.append((state, key, f"{age}d {verb}"))
    return out


def _missing_provider_keys(ids: list[str]) -> list[tuple[str, str, str]]:
    """(agent, model, credential) for every agent whose provider has no stored key; the one
    reader behind the text and JSON reports."""
    stored = _secrets.secrets_keys()
    missing: list[tuple[str, str, str]] = []
    for aid in ids:
        model = _fleet.meta_get(aid, "model", current_home().default_model)
        provider = model.split("/")[0] if "/" in model else ""
        expected = _expected_credential(provider)
        if expected and expected not in stored:
            missing.append((aid, model, expected))
    return missing


def _check_provider_coverage(ids: list[str]) -> int:
    """Warn (and count) when an agent's model provider has no stored key."""
    missing = _missing_provider_keys(ids)
    if not missing:
        return 0
    ui.section("Provider key coverage:")
    for aid, model, expected in missing:
        ui.console.print(f"[red]✗[/red]   Missing key: {aid} ({model}) — needs {expected}")
        ui.console.print(
            f"    Add with: docket setup provider add <name> <url> --credential {expected}"
        )
    return len(missing)


def _provider_catalog_problems() -> list[tuple[str, str]]:
    """Every global provider document that fails `load_provider_document`'s own
    validation -- `load_catalog` silently skips these at read time. Returns
    (name, "field: message") pairs. Read-only: never edits the catalog."""
    from pydantic import ValidationError

    raw = store.read_json(current_home().providers_file)
    providers = raw.get("providers") if isinstance(raw, dict) else None
    problems: list[tuple[str, str]] = []
    if not isinstance(providers, dict):
        return problems
    for name, block in providers.items():
        if not isinstance(block, dict):
            problems.append((str(name), "not a mapping"))
            continue
        try:
            ProviderSpec.model_validate(block)
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(p) for p in first["loc"]) if first["loc"] else ""
            problems.append((str(name), f"{field}: {first['msg']}"))
    return problems


def _check_provider_catalog() -> int:
    """Flag every malformed global provider document -- naming the file, provider
    name and failing field, the way `_check_pod_config_overlays` names a malformed
    role. Read-only: never edits the catalog."""
    ui.section("Provider catalog (docket-providers.json):")
    problems = _provider_catalog_problems()
    if not problems:
        ui.success("  All provider documents are well-formed")
        return 0
    ui.console.print("[red]✗[/red]   Found malformed docket-providers.json entries:")
    for name, reason in problems:
        ui.console.print(f"    {current_home().providers_file}: {name}: {reason}")
    return len(problems)


def _check_key_hygiene() -> int:
    """Backend + per-key age report (advisory — never fails)."""
    report = _keys_age_report()
    if not report:
        return 0
    ui.section("API key hygiene:")
    if _secrets_backend() == "keyring":
        ui.success("  Backend: keyring (values in OS keyring, not plaintext at rest)")
    else:
        ui.warn(f"  Backend: file — secrets are plaintext at rest in {current_home().secrets_file}")
        ui.dim("    For at-rest protection: DOCKET_SECRETS_BACKEND=keyring (libsecret)")
    stale = 0
    for state, name, detail in report:
        if state == "STALE":
            ui.warn(f"  {name}: {detail} — consider: docket setup provider rotate {name}")
            stale += 1
        elif state == "UNKNOWN":
            ui.dim(f"  {name}: {detail}")
        else:
            ui.success(f"  {name}: {detail}")
    if stale:
        ui.dim(f"  Rotate keys older than {current_home().key_max_age_days} days")
    return 0
