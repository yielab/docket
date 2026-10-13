"""The operator's own docket setup, read for harness contract 1.2 (ADR 0026).

A harness run's state lives in a caller-owned ``DOCKET_HOME``; the operator's setup (provider
catalog, model registry, credentials) lives in the setup home, ``DOCKET_SETUP_HOME`` or the
default home. This module reads exactly ``SETUP_FILES`` there, through a reader that takes no
lock and recovers nothing, so the setup home is never written. ``resolve_run`` is the one
decision both ``docket exec --contract 1.2`` and ``docket setup harness`` use.
See specs/api/harness-mode.spec.md "Contract 1.2".
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docket.core import models_policy as _mp
from docket.core import provider as _provider
from docket.edges import store as _store

PROVIDERS_NAME = "docket-providers.json"
MODELS_NAME = "docket-models.json"
SECRETS_NAME = "secrets.json"
SETUP_FILES = (PROVIDERS_NAME, MODELS_NAME, SECRETS_NAME)

SOURCE_EXPLICIT = "explicit"
SOURCE_SETUP_DEFAULT = "setup default"

KeyringLookup = Callable[[str], str | None]


def setup_home(environ: Mapping[str, str], default_home: Path) -> Path:
    """``DOCKET_SETUP_HOME`` when set, otherwise *default_home*."""
    raw = environ.get("DOCKET_SETUP_HOME", "").strip()
    return Path(raw).expanduser() if raw else default_home.expanduser()


@dataclass(frozen=True)
class SetupView:
    """What the setup home holds, read once: catalog, the registry's explicit choices, secrets."""

    home: Path
    catalog: _provider.Catalog
    roles: dict[str, str]
    default: str
    secrets: dict[str, str]


def load_setup(home: Path) -> SetupView:
    """Read the three setup files under *home* without writing anything there."""
    registry = _store.read_json_readonly(home / MODELS_NAME)
    raw_roles = registry.get("roles")
    roles = {
        str(role): model
        for role, model in (raw_roles.items() if isinstance(raw_roles, dict) else ())
        if isinstance(model, str) and _mp._MODEL_ID_RE.match(model)
    }
    default = registry.get("default")
    secrets = _store.read_json_readonly(home / SECRETS_NAME)
    return SetupView(
        home=home,
        catalog=_provider.catalog_from_global(_store.read_json_readonly(home / PROVIDERS_NAME)),
        roles=roles,
        default=default if isinstance(default, str) and _mp._MODEL_ID_RE.match(default) else "",
        secrets={str(k): str(v) for k, v in secrets.items()},
    )


def setup_model(view: SetupView, role: str) -> str:
    """The model the operator chose for *role*: ``roles.<role>``, then ``default``, else ``""``."""
    return view.roles.get(role) or view.default


@dataclass(frozen=True)
class Credential:
    """How a provider's credential resolved. ``value`` is never rendered anywhere."""

    needed: bool
    name: str
    source: str  # "env" | "store" | "keyring" | "none"
    value: str = ""
    keyring_failed: bool = False

    @property
    def resolves(self) -> bool:
        return not self.needed or bool(self.value)


def credential(
    spec: _provider.ProviderSpec,
    view: SetupView,
    environ: Mapping[str, str],
    keyring: KeyringLookup,
) -> Credential:
    """Resolve *spec*'s credential: ``DOCKET_LLM_API_KEY``, then per name the environment,
    ``secrets.json``'s value, or the keyring when ``secrets.json`` holds only the index."""
    override = environ.get("DOCKET_LLM_API_KEY", "").strip()
    if override:
        return Credential(True, "DOCKET_LLM_API_KEY", "env", override)
    names = tuple(spec.auth.credentials)
    if spec.auth.type == "none" or not names:
        return Credential(False, "", "none")
    for name in names:
        value = environ.get(name, "").strip()
        if value:
            return Credential(True, name, "env", value)
    keyring_failed = ""
    for name in names:
        if name not in view.secrets:
            continue
        stored = view.secrets[name].strip()
        if stored:
            return Credential(True, name, "store", stored)
        looked_up = (keyring(name) or "").strip()
        if looked_up:
            return Credential(True, name, "keyring", looked_up)
        keyring_failed = keyring_failed or name
    if keyring_failed:
        return Credential(True, keyring_failed, "none", keyring_failed=True)
    return Credential(True, names[0], "none")


@dataclass(frozen=True)
class RunSetup:
    """What a 1.2 run resolved before any network call; ``refusal`` non-empty means exit 2.
    ``spec`` is ``None`` when ``DOCKET_LLM_BASE_URL`` names the endpoint instead."""

    model: str
    source: str
    refusal: str = ""
    spec: _provider.ProviderSpec | None = None
    credential: Credential | None = None


def resolve_run(
    view: SetupView,
    *,
    role: str,
    model: str | None,
    environ: Mapping[str, str],
    keyring: KeyringLookup,
) -> RunSetup:
    """The model, provider and credential a 1.2 run uses, or the sentence that refuses it."""
    if model:
        chosen, source = model, SOURCE_EXPLICIT
    else:
        chosen, source = setup_model(view, role), SOURCE_SETUP_DEFAULT
    if not chosen:
        return RunSetup(
            "",
            source,
            f"no model is set up for role '{role}' in {view.home}; run 'docket setup model set "
            f"{role} PROVIDER/ID' (or 'docket setup provider add <name>'), or pass --model",
        )
    if environ.get("DOCKET_LLM_BASE_URL", "").strip():
        return RunSetup(chosen, source)
    provider, _, model_id = chosen.partition("/")
    if not provider or not model_id:
        return RunSetup(chosen, source, f"--model must be PROVIDER/ID, got {chosen!r}")
    spec = view.catalog.get(provider)
    if spec is None:
        return RunSetup(
            chosen,
            source,
            f"provider '{provider}' is not in docket's provider catalog ({view.home}); "
            f"add it with 'docket setup provider add {provider}'",
        )
    cred = credential(spec, view, environ, keyring)
    if cred.resolves:
        return RunSetup(chosen, source, spec=spec, credential=cred)
    if cred.keyring_failed:
        refusal = (
            f"provider '{provider}' keeps credential {cred.name} in the OS keyring, and the "
            "keyring lookup failed (no secret-tool or no D-Bus session, as inside a sandbox); "
            f"export {cred.name} in the environment, or store it in the file backend: "
            f"DOCKET_SECRETS_BACKEND=file docket setup provider add {provider}"
        )
    else:
        refusal = (
            f"provider '{provider}' needs credential {cred.name}, which is not in the "
            f"environment or in {view.home / SECRETS_NAME}; export {cred.name}, or store it "
            f"with 'docket setup provider add {provider}'"
        )
    return RunSetup(chosen, source, refusal, spec=spec, credential=cred)


def readiness(
    view: SetupView,
    *,
    role: str,
    environ: Mapping[str, str],
    keyring: KeyringLookup,
    version: str,
) -> dict[str, Any]:
    """The ``docket setup harness --json`` document: offline, and never a credential value."""
    run = resolve_run(view, role=role, model=None, environ=environ, keyring=keyring)
    providers: list[dict[str, Any]] = []
    usable: set[str] = set()
    for name in sorted(view.catalog.entries):
        spec = view.catalog.entries[name]
        cred = credential(spec, view, environ, keyring)
        if cred.resolves:
            usable.add(name)
        providers.append(
            {
                "name": name,
                "scope": view.catalog.source_of(name),
                "base_url": spec.base_url,
                "credential": {
                    "needed": cred.needed,
                    "name": cred.name,
                    "resolves": cred.resolves,
                    "source": cred.source,
                },
            }
        )
    named = {f"{p}/{row.id}" for p in usable for row in view.catalog.entries[p].models}
    named.update(m for m in (*view.roles.values(), view.default) if m.partition("/")[0] in usable)
    return {
        "v": version,
        "setup_home": str(view.home),
        "endpoint_override": bool(environ.get("DOCKET_LLM_BASE_URL", "").strip()),
        "ready": not run.refusal,
        "reason": run.refusal,
        "role": role,
        "default_model": run.model or None,
        "default_models": {r: setup_model(view, r) or None for r in _mp.ALL_ROLES},
        "models": [{"model": m, "provider": m.partition("/")[0]} for m in sorted(named)],
        "providers": providers,
    }
