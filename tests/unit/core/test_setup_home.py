"""The operator's setup as harness contract 1.2 reads it: model, provider and credential rules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docket.core import setup_home as _setup_home

SUBJECT = "docket.core.setup_home"

SECRET = "setup-home-secret-value-0123456789"


def _seed(
    home: Path,
    *,
    roles: dict[str, str] | None = None,
    default: str | None = None,
    secrets: dict[str, str] | None = None,
    auth: dict[str, object] | None = None,
) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    block = {
        "name": "stubby",
        "baseUrl": "http://127.0.0.1:9/v1",
        "auth": auth or {"type": "bearer", "credentials": ["STUBBY_API_KEY"]},
        "models": [{"id": "m1"}, {"id": "m2"}],
    }
    (home / "docket-providers.json").write_text(json.dumps({"providers": {"stubby": block}}))
    registry: dict[str, object] = {}
    if roles is not None:
        registry["roles"] = roles
    if default is not None:
        registry["default"] = default
    (home / "docket-models.json").write_text(json.dumps(registry))
    if secrets is not None:
        (home / "secrets.json").write_text(json.dumps(secrets))
    return home


def _no_keyring(name: str) -> str | None:
    return None


def _resolve(home: Path, model: str | None = None, **environ: str) -> _setup_home.RunSetup:
    view = _setup_home.load_setup(home)
    return _setup_home.resolve_run(
        view, role="implementer", model=model, environ=environ, keyring=_no_keyring
    )


def test_setup_home_is_docket_setup_home_when_set(tmp_path: Path) -> None:
    env = {"DOCKET_SETUP_HOME": str(tmp_path / "s")}
    assert _setup_home.setup_home(env, tmp_path / "d") == tmp_path / "s"
    assert _setup_home.setup_home({}, tmp_path / "d") == tmp_path / "d"


def test_an_omitted_model_uses_the_roles_registry_model(tmp_path: Path) -> None:
    home = _seed(tmp_path, roles={"implementer": "stubby/m1"}, default="stubby/m2")
    run = _resolve(home, STUBBY_API_KEY=SECRET)
    assert (run.model, run.source, run.refusal) == ("stubby/m1", "setup default", "")


def test_an_omitted_model_falls_back_to_the_registry_default(tmp_path: Path) -> None:
    home = _seed(tmp_path, roles={"lead": "stubby/m1"}, default="stubby/m2")
    run = _resolve(home, STUBBY_API_KEY=SECRET)
    assert (run.model, run.source) == ("stubby/m2", "setup default")


def test_an_explicit_model_is_recorded_explicit(tmp_path: Path) -> None:
    home = _seed(tmp_path, default="stubby/m2")
    run = _resolve(home, "stubby/m1", STUBBY_API_KEY=SECRET)
    assert (run.model, run.source) == ("stubby/m1", "explicit")


def test_no_model_in_the_registry_refuses_with_the_setup_command(tmp_path: Path) -> None:
    run = _resolve(_seed(tmp_path))
    assert "no model is set up for role 'implementer'" in run.refusal
    assert "docket setup model set implementer PROVIDER/ID" in run.refusal


def test_a_provider_missing_from_the_catalog_refuses(tmp_path: Path) -> None:
    run = _resolve(_seed(tmp_path, default="nowhere/m1"))
    assert "provider 'nowhere' is not in docket's provider catalog" in run.refusal


def test_a_missing_credential_refuses_naming_provider_and_name(tmp_path: Path) -> None:
    run = _resolve(_seed(tmp_path, default="stubby/m1"))
    assert "provider 'stubby' needs credential STUBBY_API_KEY" in run.refusal


def test_a_keyring_index_whose_lookup_fails_refuses_and_names_the_file_backend(
    tmp_path: Path,
) -> None:
    run = _resolve(_seed(tmp_path, default="stubby/m1", secrets={"STUBBY_API_KEY": ""}))
    assert "keeps credential STUBBY_API_KEY in the OS keyring" in run.refusal
    assert "keyring lookup failed" in run.refusal
    assert "DOCKET_SECRETS_BACKEND=file" in run.refusal


def test_a_keyring_index_resolves_through_the_lookup(tmp_path: Path) -> None:
    view = _setup_home.load_setup(
        _seed(tmp_path, default="stubby/m1", secrets={"STUBBY_API_KEY": ""})
    )
    run = _setup_home.resolve_run(
        view, role="implementer", model=None, environ={}, keyring=lambda name: SECRET
    )
    assert run.refusal == ""
    assert run.credential is not None
    assert (run.credential.source, run.credential.value) == ("keyring", SECRET)


def test_the_environment_wins_over_the_store(tmp_path: Path) -> None:
    home = _seed(tmp_path, default="stubby/m1", secrets={"STUBBY_API_KEY": "stored-value-xyz"})
    run = _resolve(home, STUBBY_API_KEY=SECRET)
    assert run.credential is not None
    assert (run.credential.source, run.credential.value) == ("env", SECRET)


def test_a_provider_that_needs_no_credential_resolves_without_one(tmp_path: Path) -> None:
    run = _resolve(_seed(tmp_path, default="stubby/m1", auth={"type": "none"}))
    assert run.refusal == ""
    assert run.credential is not None and not run.credential.needed


def test_no_refusal_sentence_ever_contains_a_credential_value(tmp_path: Path) -> None:
    home = _seed(tmp_path, default="nowhere/m1", secrets={"STUBBY_API_KEY": SECRET})
    assert SECRET not in _resolve(home).refusal


@pytest.mark.parametrize(
    "secrets", [{"STUBBY_API_KEY": SECRET}, {"STUBBY_API_KEY": ""}, None], ids=str
)
def test_readiness_reason_is_the_run_refusal(
    tmp_path: Path, secrets: dict[str, str] | None
) -> None:
    view = _setup_home.load_setup(_seed(tmp_path, default="stubby/m1", secrets=secrets))
    doc = _setup_home.readiness(
        view, role="implementer", environ={}, keyring=_no_keyring, version="1.2.0"
    )
    run = _setup_home.resolve_run(
        view, role="implementer", model=None, environ={}, keyring=_no_keyring
    )
    assert doc["ready"] is (run.refusal == "")
    assert doc["reason"] == run.refusal
    assert SECRET not in json.dumps(doc)


def test_readiness_lists_models_only_of_providers_whose_credential_resolves(
    tmp_path: Path,
) -> None:
    view = _setup_home.load_setup(
        _seed(tmp_path, roles={"implementer": "stubby/m1"}, secrets={"STUBBY_API_KEY": SECRET})
    )
    doc = _setup_home.readiness(
        view, role="implementer", environ={}, keyring=_no_keyring, version="1.2.0"
    )
    assert {"model": "stubby/m1", "provider": "stubby"} in doc["models"]
    assert doc["default_models"]["implementer"] == "stubby/m1"
    assert doc["default_models"]["lead"] is None
    stubby = next(p for p in doc["providers"] if p["name"] == "stubby")
    assert stubby["credential"] == {
        "needed": True,
        "name": "STUBBY_API_KEY",
        "resolves": True,
        "source": "store",
    }
    unresolved = [p["name"] for p in doc["providers"] if not p["credential"]["resolves"]]
    assert all(not m["model"].startswith(f"{name}/") for m in doc["models"] for name in unresolved)


def test_loading_the_setup_home_writes_nothing_there(tmp_path: Path) -> None:
    home = _seed(tmp_path, default="stubby/m1", secrets={"STUBBY_API_KEY": SECRET})
    before = {p.name: p.stat().st_mtime_ns for p in home.iterdir()}
    _setup_home.readiness(
        _setup_home.load_setup(home),
        role="implementer",
        environ={},
        keyring=_no_keyring,
        version="1.2.0",
    )
    assert {p.name: p.stat().st_mtime_ns for p in home.iterdir()} == before
