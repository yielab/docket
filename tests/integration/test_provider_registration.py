"""Provider registration (`docket models provider add/list/show/remove/export`).

Registration verifies `<base-url>/models` **with the resolved credential** and classifies the
result (ADR 0011 §4) instead of collapsing it to a boolean: only a transport failure refuses;
every HTTP status registers, with a warning when it is not a clean 200.
`core.provider.verify_endpoint` is the pure classifier; `edges.adapters.llm.probe_models` is the
one function that opens a socket; `core.provider.register_provider` wires them together and
persists only when reachable. See specs/functional/model-profiles.spec.md "Provider readiness".
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest
from tests.conftest import repoint_docket_home
from typer.testing import CliRunner

from docket.cli import app as _app
from docket.core import fleet as _fleet
from docket.core import provider as _prov
from docket.edges.adapters.llm import ProbeResult

SUBJECT = "docket.core"

_runner = CliRunner()

# Minimal fleet.json seed (no providers yet).
_FLEET_CONFIG: dict[str, Any] = {
    "agents": [],
    "bindings": [],
    "defaults": {"model": "anthropic/claude-sonnet-4-6"},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}


def _seed(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = root / ".docket"
    home.mkdir(parents=True)
    fleet_file = home / "fleet.json"
    fleet_file.write_text(json.dumps(_FLEET_CONFIG))
    fleet_file.chmod(0o600)
    repoint_docket_home(monkeypatch, home)
    return home


def _providers(home: Path) -> dict[str, Any]:
    catalog_file = home / "docket-providers.json"
    if not catalog_file.is_file():
        return {}
    cfg = json.loads(catalog_file.read_text())
    providers = cfg.get("providers", {})
    assert isinstance(providers, dict)
    return providers


@contextlib.contextmanager
def _serve(status: int, body: bytes = b'{"data": []}') -> Iterator[str]:
    """A real local HTTP server answering every GET with *status*/*body* -- the fake-endpoint
    pattern `tests/unit/edges/adapters/test_fetch.py` uses. Yields its base URL."""

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:  # quiet the test output
            pass

        def do_GET(self) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    finally:
        srv.shutdown()
        thread.join(timeout=5)


# ── core: verify_endpoint is a pure classifier over an injected ProbeResult ────


class TestVerifyEndpointClassification:
    def test_transport_failure_is_the_only_unreachable_outcome(self) -> None:
        spec = _prov.ProviderSpec(
            name="deadend",
            dialect="openai-chat",
            base_url="http://127.0.0.1:1/v1",
            auth=_prov.AuthSpec(type="none"),
        )
        verification = _prov.verify_endpoint(
            spec, ProbeResult(status=None, transport_error="refused")
        )
        assert verification.reachable is False
        assert verification.warning == "refused"

    def test_401_without_a_credential_registers_reachable_and_names_it(self) -> None:
        spec = _prov.ProviderSpec(
            name="hosted",
            dialect="openai-chat",
            base_url="https://example.test/v1",
            auth=_prov.AuthSpec(type="bearer", credentials=["HOSTED_API_KEY"]),
        )
        verification = _prov.verify_endpoint(spec, ProbeResult(status=401))
        assert verification.reachable is True
        assert verification.credential_present is False
        assert "HOSTED_API_KEY" in verification.warning


# ── cli: a local http.server backs every network-shaped assertion ──────────────


def test_add_registers_at_401_with_a_warning_naming_the_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED on the base: `ping_endpoint`/`register_local_provider` treat any HTTPError
    (including a 401) as unreachable and refuse with "Provider was not registered"."""
    home = _seed(tmp_path, monkeypatch)
    with _serve(401, b'{"error": "no key"}') as base_url:
        result = _runner.invoke(
            _app,
            [
                "models",
                "provider",
                "add",
                "hosted",
                base_url,
                "--model",
                "m",
                "--credential",
                "HOSTED_API_KEY",
            ],
        )
    assert result.exit_code == 0, result.stdout
    entry = _providers(home)["hosted"]
    assert entry["baseUrl"] == base_url
    assert entry["auth"] == {"type": "bearer", "credentials": ["HOSTED_API_KEY"]}
    assert "HOSTED_API_KEY" in result.stdout


def test_add_refuses_on_transport_failure_and_does_not_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The kept negative case: a transport failure is the one outcome that still refuses and
    leaves the catalog untouched."""
    home = _seed(tmp_path, monkeypatch)
    result = _runner.invoke(
        _app,
        ["models", "provider", "add", "deadend", "http://127.0.0.1:1/v1", "--model", "m"],
    )
    assert result.exit_code == 1
    assert _providers(home) == {}
    assert not (home / "docket-providers.json").exists()
    assert "Could not reach" in result.stderr
    assert "Provider was not registered" in result.stderr


def test_add_at_200_reports_unadvertised_ids_as_a_suggestion_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _seed(tmp_path, monkeypatch)
    body = json.dumps({"data": [{"id": "known"}, {"id": "extra-model"}]}).encode()
    with _serve(200, body) as base_url:
        result = _runner.invoke(
            _app, ["models", "provider", "add", "hosted2", base_url, "--model", "known"]
        )
    assert result.exit_code == 0, result.stdout
    assert "extra-model" in result.stdout
    stored_ids = {row["id"] for row in _providers(home)["hosted2"]["models"]}
    assert stored_ids == {"known"}  # a suggestion is printed, never written


def test_export_then_add_round_trips_through_show_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path / "a", monkeypatch)
    with _serve(200, b'{"data": []}') as base_url:
        added_a = _runner.invoke(
            _app,
            [
                "models",
                "provider",
                "add",
                "roundtrip",
                base_url,
                "--model",
                "m",
                "--ctx",
                "4096",
                "--max-tokens",
                "1024",
            ],
        )
        assert added_a.exit_code == 0, added_a.stdout
        show_a = _runner.invoke(_app, ["models", "provider", "show", "roundtrip", "--json"])
        assert show_a.exit_code == 0, show_a.stdout

        export_file = tmp_path / "roundtrip.yaml"
        exported = _runner.invoke(
            _app, ["models", "provider", "export", "roundtrip", str(export_file)]
        )
        assert exported.exit_code == 0, exported.stdout
        assert export_file.read_text().startswith("kind: provider\n")

        _seed(tmp_path / "b", monkeypatch)
        added_b = _runner.invoke(_app, ["models", "provider", "add", str(export_file)])
        assert added_b.exit_code == 0, added_b.stdout
        show_b = _runner.invoke(_app, ["models", "provider", "show", "roundtrip", "--json"])
        assert show_b.exit_code == 0, show_b.stdout

    assert json.loads(show_a.stdout) == json.loads(show_b.stdout)


def test_preset_anthropic_on_fresh_home_names_the_missing_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A built-in hosted preset needs only its credential -- the built-in document is the
    registration; no separate `provider add` is required for it to apply."""
    _seed(tmp_path, monkeypatch)
    result = _runner.invoke(_app, ["models", "preset", "anthropic"])
    assert result.exit_code == 0, result.stdout
    assert "ANTHROPIC_API_KEY" in result.stdout


def test_remove_refuses_for_a_built_in_with_no_global_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path, monkeypatch)
    result = _runner.invoke(_app, ["models", "provider", "remove", "anthropic"])
    assert result.exit_code == 1
    assert "built-in" in result.stderr.lower()


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
