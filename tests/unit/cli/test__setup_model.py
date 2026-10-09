"""`docket setup provider` credentials -- no per-agent file propagation, and the keyring backend actually
stores (not just looks up).

Nothing on the live turn path reads a per-agent file for credentials --
`edges/adapters/llm.py` resolves them through `core/secrets.py` directly, so
credentials are written nowhere else. Under `DOCKET_SECRETS_BACKEND=keyring`, add/rotate store
through `secret-tool store` and fail closed (never falling back to plaintext) if that
fails; remove clears the keyring entry too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home
from typer.testing import CliRunner

import docket.edges.adapters.system as _system_mod
from docket.cli import _setup_model, app
from docket.core import models_policy as _mp
from docket.core import provider as _prov
from docket.core import secrets as _secrets

SUBJECT = "docket.cli._setup_model"

_runner = CliRunner()


def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    repoint_docket_home(monkeypatch, home)
    return home


def _seed_workspace(home: Path, agent_id: str = "demo") -> Path:
    ws = home / "workspaces" / "projects" / agent_id
    ws.mkdir(parents=True)
    (ws / ".docket-meta.json").write_text('{"model": "anthropic/claude-sonnet-4-6"}')
    return ws


# ── no per-agent .env propagation ────────────────────────────────────────────────


class TestNoEnvSync:
    def test_credential_add_creates_no_env_in_any_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        ws = _seed_workspace(home)
        monkeypatch.setattr(
            _setup_model._getpass, "getpass", lambda *a, **k: "fake-ant-testvalue00000000000000"
        )

        rc = _setup_model.credential_add("ANTHROPIC_API_KEY")

        assert rc == 0
        assert not (ws / ".env").exists()
        assert list(ws.iterdir()) == [ws / ".docket-meta.json"]

    def test_credential_rotate_creates_no_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        ws = _seed_workspace(home)
        monkeypatch.setattr(
            _setup_model._getpass, "getpass", lambda *a, **k: "fake-ant-firstvalue000000"
        )
        _setup_model.credential_add("ANTHROPIC_API_KEY")

        monkeypatch.setattr(
            _setup_model._getpass, "getpass", lambda *a, **k: "fake-ant-secondvalue00000"
        )
        rc = _setup_model.credential_rotate("ANTHROPIC_API_KEY")

        assert rc == 0
        assert not (ws / ".env").exists()

    def test_credential_remove_creates_no_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        ws = _seed_workspace(home)
        monkeypatch.setattr(
            _setup_model._getpass, "getpass", lambda *a, **k: "fake-ant-testvalue00000000000000"
        )
        _setup_model.credential_add("ANTHROPIC_API_KEY")
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        rc = _setup_model.credential_remove("ANTHROPIC_API_KEY")

        assert rc == 0
        assert not (ws / ".env").exists()


# ── keyring backend: add/rotate actually store, not just look up ────────────────


class TestKeyringBackendStores:
    def test_add_stores_through_secret_tool_not_secrets_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        monkeypatch.setenv("DOCKET_SECRETS_BACKEND", "keyring")
        monkeypatch.setattr(_system_mod, "secret_tool_available", lambda: True)
        stored: dict[str, str] = {}
        monkeypatch.setattr(
            _system_mod,
            "secret_tool_store",
            lambda service, key, value: stored.setdefault(key, value) or True,
        )
        monkeypatch.setattr(
            _setup_model._getpass, "getpass", lambda *a, **k: "fake-ant-realvalue0000000"
        )

        rc = _setup_model.credential_add("ANTHROPIC_API_KEY")

        assert rc == 0
        assert stored == {"ANTHROPIC_API_KEY": "fake-ant-realvalue0000000"}
        on_disk = json.loads(_secrets.SECRETS_FILE.read_text())
        assert on_disk["ANTHROPIC_API_KEY"] == ""

    def test_add_fails_closed_when_secret_tool_store_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        monkeypatch.setenv("DOCKET_SECRETS_BACKEND", "keyring")
        monkeypatch.setattr(_system_mod, "secret_tool_available", lambda: True)
        monkeypatch.setattr(_system_mod, "secret_tool_store", lambda *a, **k: False)
        monkeypatch.setattr(
            _setup_model._getpass, "getpass", lambda *a, **k: "fake-ant-realvalue0000000"
        )

        rc = _setup_model.credential_add("ANTHROPIC_API_KEY")

        assert rc == 1
        assert not _secrets.SECRETS_FILE.exists() or "ANTHROPIC_API_KEY" not in json.loads(
            _secrets.SECRETS_FILE.read_text() or "{}"
        )

    def test_rotate_stores_through_secret_tool(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        # First add under the file backend so the key exists to rotate.
        monkeypatch.setattr(
            _setup_model._getpass, "getpass", lambda *a, **k: "fake-ant-original00000000"
        )
        _setup_model.credential_add("ANTHROPIC_API_KEY")

        monkeypatch.setenv("DOCKET_SECRETS_BACKEND", "keyring")
        monkeypatch.setattr(_system_mod, "secret_tool_available", lambda: True)
        stored: dict[str, str] = {}
        monkeypatch.setattr(
            _system_mod,
            "secret_tool_store",
            lambda service, key, value: stored.setdefault(key, value) or True,
        )
        monkeypatch.setattr(
            _setup_model._getpass, "getpass", lambda *a, **k: "fake-ant-rotated000000000"
        )

        rc = _setup_model.credential_rotate("ANTHROPIC_API_KEY")

        assert rc == 0
        assert stored == {"ANTHROPIC_API_KEY": "fake-ant-rotated000000000"}
        on_disk = json.loads(_secrets.SECRETS_FILE.read_text())
        assert on_disk["ANTHROPIC_API_KEY"] == ""

    def test_remove_clears_the_keyring_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        monkeypatch.setenv("DOCKET_SECRETS_BACKEND", "keyring")
        monkeypatch.setattr(_system_mod, "secret_tool_available", lambda: True)
        monkeypatch.setattr(_system_mod, "secret_tool_store", lambda *a, **k: True)
        monkeypatch.setattr(
            _setup_model._getpass, "getpass", lambda *a, **k: "fake-ant-realvalue0000000"
        )
        _setup_model.credential_add("ANTHROPIC_API_KEY")

        cleared: list[str] = []
        monkeypatch.setattr(
            _system_mod, "secret_tool_clear", lambda service, key: cleared.append(key) or True
        )
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        rc = _setup_model.credential_remove("ANTHROPIC_API_KEY")

        assert rc == 0
        assert cleared == ["ANTHROPIC_API_KEY"]
        assert "ANTHROPIC_API_KEY" not in json.loads(_secrets.SECRETS_FILE.read_text())


class TestFileBackendUnaffected:
    def test_add_still_stores_the_real_value_in_secrets_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        monkeypatch.setattr(
            _setup_model._getpass, "getpass", lambda *a, **k: "fake-ant-realvalue0000000"
        )

        rc = _setup_model.credential_add("ANTHROPIC_API_KEY")

        assert rc == 0
        on_disk = json.loads(_secrets.SECRETS_FILE.read_text())
        assert on_disk["ANTHROPIC_API_KEY"] == "fake-ant-realvalue0000000"


# -- provider add ----------------------------------------------------------------------------


class TestProviderAdd:
    @staticmethod
    def _reachable(monkeypatch: pytest.MonkeyPatch) -> None:
        from docket.edges.adapters import llm as _llm

        monkeypatch.setattr(_llm, "probe_models", lambda *a, **k: _llm.ProbeResult(status=200))

    def test_hosted_provider_stores_the_credential_and_applies_the_preset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        self._reachable(monkeypatch)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        result = _runner.invoke(
            app, ["setup", "provider", "add", "anthropic", "--credential", "fake-ant-" + "x" * 40]
        )

        assert result.exit_code == 0, result.stdout + result.stderr
        assert "ANTHROPIC_API_KEY" in _secrets.load_secrets()
        assert "lead" in result.stdout
        assert _mp.resolve_role_model("lead").startswith("anthropic/")

    def test_no_preset_leaves_the_role_rows_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        self._reachable(monkeypatch)

        result = _runner.invoke(
            app, ["setup", "provider", "add", "x", "http://127.0.0.1:9/v1", "--no-preset"]
        )

        assert result.exit_code == 0, result.stdout + result.stderr
        assert "x" in json.loads((home / "docket-providers.json").read_text())["providers"]
        assert not (home / "docket-models.json").exists()

    def test_a_hosted_provider_off_a_terminal_without_a_credential_fails_naming_the_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        result = _runner.invoke(app, ["setup", "provider", "add", "anthropic"])

        assert result.exit_code == 1
        assert "--credential" in result.stderr
        assert not (home / "docket-providers.json").exists()

    def test_piped_remove_without_yes_fails_naming_the_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        _prov.save_provider(
            _prov.ProviderSpec(
                name="x", baseUrl="http://127.0.0.1:9/v1", auth=_prov.AuthSpec(type="none")
            )
        )

        result = _runner.invoke(app, ["setup", "provider", "remove", "x"])

        assert result.exit_code == 1
        assert "--yes" in result.stderr

    def test_model_set_rejects_an_unknown_role(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)

        result = _runner.invoke(app, ["setup", "model", "set", "unicorn", "anthropic/claude-x"])

        assert result.exit_code == 1


class TestProviderAddAdvertisedModel:
    @staticmethod
    def _probe(monkeypatch: pytest.MonkeyPatch, ids: tuple[str, ...]) -> list[int]:
        from docket.edges.adapters import llm as _llm

        calls: list[int] = []

        def fake(*a: object, **k: object) -> _llm.ProbeResult:
            calls.append(1)
            return _llm.ProbeResult(status=200, model_ids=list(ids))

        monkeypatch.setattr(_llm, "probe_models", fake)
        return calls

    @staticmethod
    def _row(name: str) -> str:
        spec = _prov.load_catalog().get(name)
        assert spec is not None
        return spec.models[0].id

    def test_first_advertised_id_becomes_the_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No --model: the row is the first sorted advertised id, probed once."""
        _home(tmp_path, monkeypatch)
        calls = self._probe(monkeypatch, ("qwen-x", "abc"))

        result = _runner.invoke(
            app, ["setup", "provider", "add", "custom", "http://127.0.0.1:1/v1"]
        )

        assert result.exit_code == 0, result.stdout + result.stderr
        assert self._row("custom") == "abc"
        assert "abc" in result.stdout
        assert "also advertises: abc" not in result.stdout
        assert len(calls) == 1

    def test_no_advertised_id_keeps_local_model_and_says_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty advertisement leaves local-model and the output names that."""
        _home(tmp_path, monkeypatch)
        self._probe(monkeypatch, ())

        result = _runner.invoke(
            app, ["setup", "provider", "add", "custom", "http://127.0.0.1:1/v1"]
        )

        assert result.exit_code == 0, result.stdout + result.stderr
        assert self._row("custom") == "local-model"
        assert "no model advertised" in result.stdout

    def test_explicit_model_wins_over_the_advertisement(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--model mine is recorded whatever the probe advertised."""
        _home(tmp_path, monkeypatch)
        self._probe(monkeypatch, ("qwen-x", "abc"))

        result = _runner.invoke(
            app,
            ["setup", "provider", "add", "custom", "http://127.0.0.1:1/v1", "--model", "mine"],
        )

        assert result.exit_code == 0, result.stdout + result.stderr
        assert self._row("custom") == "mine"
