"""Local provider registration (models provider add).

`core.provider.register_local_provider` is the pure ping->register orchestration (no output);
`cli._provider.run_provider_add` renders it. We assert the resulting `docket-providers.json`
document, that a re-run is a no-op, and the cli layer's wording. See
specs/functional/model-profiles.spec.md "Provider catalog" -- the per-model display caption a
pre-catalog fleet.json block carried was display-only and has no field in the document.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home
from typer.testing import CliRunner

from docket.cli import _provider as _cliprov
from docket.cli import app as _app
from docket.core import fleet as _fleet
from docket.core import provider as _prov

SUBJECT = "docket.core"

_runner = CliRunner()

# Minimal fleet.json seed (no providers yet).
_FLEET_CONFIG: dict[str, Any] = {
    "agents": [],
    "bindings": [],
    "defaults": {"model": "anthropic/claude-sonnet-4-6"},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    home.mkdir()
    fleet_file = home / "fleet.json"
    fleet_file.write_text(json.dumps(_FLEET_CONFIG))
    fleet_file.chmod(0o600)
    repoint_docket_home(monkeypatch, home)
    # Default: the hermetic endpoint edge is reachable; individual rejection tests override it.
    monkeypatch.setattr(_prov, "ping_endpoint", lambda *a, **k: True)
    return home


def _providers(home: Path) -> dict[str, Any]:
    catalog_file = home / "docket-providers.json"
    if not catalog_file.is_file():
        return {}
    cfg = json.loads(catalog_file.read_text())
    providers = cfg.get("providers", {})
    assert isinstance(providers, dict)
    return providers


# ── core: pure ping → register orchestration, no output ────────────────────────


def test_register_local_provider_returns_typed_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(tmp_path, monkeypatch)
    reg = _prov.register_local_provider()
    assert reg.name == _prov.DEFAULT_PROVIDER
    assert reg.base_url == _prov.DEFAULT_BASE_URL
    assert reg.model_id == _prov.DEFAULT_MODEL_ID
    assert reg.reachable is True
    assert reg.changed is True  # first write
    # Pure orchestration — core/ prints nothing.
    assert capsys.readouterr().out == ""


def test_register_local_provider_writes_a_provider_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _seed(tmp_path, monkeypatch)
    _prov.register_local_provider(
        name="lab",
        base_url="http://10.0.0.5:1234/v1",
        model_id="llama-3.3-70b",
        model_name="Llama 3.3 70B",
        ctx=32768,
        max_tokens=4096,
    )
    entry = _providers(home)["lab"]
    assert entry["baseUrl"] == "http://10.0.0.5:1234/v1"
    assert entry["dialect"] == "openai-chat"
    assert entry["local"] is True
    assert entry["auth"] == {"type": "none", "header": "", "credentials": []}
    assert entry["models"] == [{"id": "llama-3.3-70b", "contextWindow": 32768, "maxTokens": 4096}]
    # The display-only per-model caption was retired: the document has no home for it.
    assert "name" not in entry["models"][0]
    assert "apiKey" not in entry
    assert "api" not in entry


def test_register_local_provider_does_not_touch_fleet_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _seed(tmp_path, monkeypatch)
    before = (home / "fleet.json").read_text()
    _prov.register_local_provider()
    after = (home / "fleet.json").read_text()
    assert before == after


def test_rerun_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(tmp_path, monkeypatch)
    first = _prov.register_local_provider()
    second = _prov.register_local_provider()
    assert first.changed is True
    assert second.changed is False


def test_changing_context_window_is_a_real_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _seed(tmp_path, monkeypatch)
    assert _prov.register_local_provider(name="local", ctx=8192).changed is True
    assert _prov.register_local_provider(name="local", ctx=16384).changed is True
    entry = _providers(home)["local"]
    assert entry["models"][0]["contextWindow"] == 16384


# ── cli: renders the result, wording matches the pre-split flow ────────────────


def test_run_provider_add_writes_provider_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _seed(tmp_path, monkeypatch)
    rc = _cliprov.run_provider_add()
    assert rc == 0

    providers = _providers(home)
    assert set(providers) == {"local"}
    assert providers["local"]["baseUrl"] == _prov.DEFAULT_BASE_URL
    assert providers["local"]["models"][0]["id"] == _prov.DEFAULT_MODEL_ID

    captured = capsys.readouterr()
    out = captured.out + captured.err
    # Role-split commands are printed as in the script.
    assert "docket models preset local" in out
    assert "anthropic/" not in out


def test_rerun_is_noop_through_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _seed(tmp_path, monkeypatch)
    _cliprov.run_provider_add(model_id="q", model_name="Q")
    capsys.readouterr()

    before = (home / "docket-providers.json").read_text()
    _cliprov.run_provider_add(model_id="q", model_name="Q")
    out = capsys.readouterr().out
    after = (home / "docket-providers.json").read_text()
    assert before == after
    assert "no change" in out


def test_ping_failure_is_fail_closed_and_does_not_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _seed(tmp_path, monkeypatch)
    monkeypatch.setattr(_prov, "ping_endpoint", lambda *a, **k: False)

    rc = _cliprov.run_provider_add()
    assert rc == 1
    assert _providers(home) == {}
    assert not (home / "docket-providers.json").exists()
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "Could not reach" in out
    assert "Provider was not registered" in out


def test_run_provider_add_output_order_matches_pre_split_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Checking -> ping -> registering -> success/no-change -> keyless local guidance."""
    _seed(tmp_path, monkeypatch)
    _cliprov.run_provider_add()
    out = capsys.readouterr().out
    checking_idx = out.index("Checking the endpoint is alive")
    registering_idx = out.index("Registering provider")
    wired_idx = out.index("Local provider wired")
    role_split_idx = out.index("Next — select the reachable local provider")
    assert checking_idx < registering_idx < wired_idx < role_split_idx


def test_run_provider_add_through_the_full_cli_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _seed(tmp_path, monkeypatch)
    result = _runner.invoke(
        _app,
        [
            "models",
            "provider",
            "add",
            "lab",
            "http://10.0.0.5:1234/v1",
            "--model",
            "llama-3.3-70b",
        ],
    )
    assert result.exit_code == 0, result.stdout
    entry = _providers(home)["lab"]
    assert entry["models"][0]["id"] == "llama-3.3-70b"


# ── the fleet.json → catalog migration ──────────────────────────────────────────


def test_fleet_providers_migrate_into_the_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-catalog `fleet.json -> providers` block (`_fleet.load_fleet`'s own shape) still
    resolves through `load_catalog`, and is ported into the document once."""
    home = _seed(tmp_path, monkeypatch)
    fleet_cfg = json.loads((home / "fleet.json").read_text())
    fleet_cfg["providers"] = {
        "legacy": {
            "baseUrl": "http://127.0.0.1:8082/v1",
            "apiKey": "local",
            "models": [{"id": "m", "contextWindow": 8192, "maxTokens": 2048}],
        }
    }
    (home / "fleet.json").write_text(json.dumps(fleet_cfg))

    catalog = _prov.load_catalog()

    assert catalog.get("legacy") is not None
    assert catalog.source_of("legacy") == "global"
    assert _fleet.load_fleet().providers == {}
