"""`docket keys` -- no per-agent file propagation, and the keyring backend actually
stores (not just looks up).

Nothing on the live turn path reads a per-agent file for credentials --
`edges/adapters/llm.py` resolves them through `core/secrets.py` directly, so `keys`
writes nowhere else. Under `DOCKET_SECRETS_BACKEND=keyring`, `add`/`rotate` store
through `secret-tool store` and fail closed (never falling back to plaintext) if that
fails; `remove` clears the keyring entry too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

import docket.edges.adapters.system as _system_mod
from docket.cli import _keys
from docket.core import secrets as _secrets

SUBJECT = "docket.cli._keys"


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
    def test_keys_add_creates_no_env_in_any_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        ws = _seed_workspace(home)
        monkeypatch.setattr(
            _keys._getpass, "getpass", lambda *a, **k: "sk-ant-testvalue00000000000000"
        )

        rc = _keys.run_keys("add", ["ANTHROPIC_API_KEY"])

        assert rc == 0
        assert not (ws / ".env").exists()
        assert list(ws.iterdir()) == [ws / ".docket-meta.json"]

    def test_keys_rotate_creates_no_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        ws = _seed_workspace(home)
        monkeypatch.setattr(_keys._getpass, "getpass", lambda *a, **k: "sk-ant-firstvalue000000")
        _keys.run_keys("add", ["ANTHROPIC_API_KEY"])

        monkeypatch.setattr(_keys._getpass, "getpass", lambda *a, **k: "sk-ant-secondvalue00000")
        rc = _keys.run_keys("rotate", ["ANTHROPIC_API_KEY"])

        assert rc == 0
        assert not (ws / ".env").exists()

    def test_keys_remove_creates_no_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        ws = _seed_workspace(home)
        monkeypatch.setattr(
            _keys._getpass, "getpass", lambda *a, **k: "sk-ant-testvalue00000000000000"
        )
        _keys.run_keys("add", ["ANTHROPIC_API_KEY"])
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        rc = _keys.run_keys("remove", ["ANTHROPIC_API_KEY"])

        assert rc == 0
        assert not (ws / ".env").exists()

    def test_sync_keys_to_agents_no_longer_exists(self) -> None:
        """Pins the removal itself -- the function is gone, not merely unreachable."""
        assert not hasattr(_keys, "_sync_keys_to_agents")


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
        monkeypatch.setattr(_keys._getpass, "getpass", lambda *a, **k: "sk-ant-realvalue0000000")

        rc = _keys.run_keys("add", ["ANTHROPIC_API_KEY"])

        assert rc == 0
        assert stored == {"ANTHROPIC_API_KEY": "sk-ant-realvalue0000000"}
        on_disk = json.loads(_secrets.SECRETS_FILE.read_text())
        assert on_disk["ANTHROPIC_API_KEY"] == ""

    def test_add_fails_closed_when_secret_tool_store_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        monkeypatch.setenv("DOCKET_SECRETS_BACKEND", "keyring")
        monkeypatch.setattr(_system_mod, "secret_tool_available", lambda: True)
        monkeypatch.setattr(_system_mod, "secret_tool_store", lambda *a, **k: False)
        monkeypatch.setattr(_keys._getpass, "getpass", lambda *a, **k: "sk-ant-realvalue0000000")

        rc = _keys.run_keys("add", ["ANTHROPIC_API_KEY"])

        assert rc == 1
        assert not _secrets.SECRETS_FILE.exists() or "ANTHROPIC_API_KEY" not in json.loads(
            _secrets.SECRETS_FILE.read_text() or "{}"
        )

    def test_rotate_stores_through_secret_tool(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        # First add under the file backend so the key exists to rotate.
        monkeypatch.setattr(_keys._getpass, "getpass", lambda *a, **k: "sk-ant-original00000000")
        _keys.run_keys("add", ["ANTHROPIC_API_KEY"])

        monkeypatch.setenv("DOCKET_SECRETS_BACKEND", "keyring")
        monkeypatch.setattr(_system_mod, "secret_tool_available", lambda: True)
        stored: dict[str, str] = {}
        monkeypatch.setattr(
            _system_mod,
            "secret_tool_store",
            lambda service, key, value: stored.setdefault(key, value) or True,
        )
        monkeypatch.setattr(_keys._getpass, "getpass", lambda *a, **k: "sk-ant-rotated000000000")

        rc = _keys.run_keys("rotate", ["ANTHROPIC_API_KEY"])

        assert rc == 0
        assert stored == {"ANTHROPIC_API_KEY": "sk-ant-rotated000000000"}
        on_disk = json.loads(_secrets.SECRETS_FILE.read_text())
        assert on_disk["ANTHROPIC_API_KEY"] == ""

    def test_remove_clears_the_keyring_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        monkeypatch.setenv("DOCKET_SECRETS_BACKEND", "keyring")
        monkeypatch.setattr(_system_mod, "secret_tool_available", lambda: True)
        monkeypatch.setattr(_system_mod, "secret_tool_store", lambda *a, **k: True)
        monkeypatch.setattr(_keys._getpass, "getpass", lambda *a, **k: "sk-ant-realvalue0000000")
        _keys.run_keys("add", ["ANTHROPIC_API_KEY"])

        cleared: list[str] = []
        monkeypatch.setattr(
            _system_mod, "secret_tool_clear", lambda service, key: cleared.append(key) or True
        )
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        rc = _keys.run_keys("remove", ["ANTHROPIC_API_KEY"])

        assert rc == 0
        assert cleared == ["ANTHROPIC_API_KEY"]
        assert "ANTHROPIC_API_KEY" not in json.loads(_secrets.SECRETS_FILE.read_text())

    def test_list_resolves_the_real_value_from_the_keyring(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        real_value = "sk-ant-" + "b" * 40  # valid format: prefix + >= 40 chars
        _home(tmp_path, monkeypatch)
        monkeypatch.setenv("DOCKET_SECRETS_BACKEND", "keyring")
        monkeypatch.setattr(_system_mod, "secret_tool_available", lambda: True)
        monkeypatch.setattr(_system_mod, "secret_tool_store", lambda *a, **k: True)
        monkeypatch.setattr(_keys._getpass, "getpass", lambda *a, **k: real_value)
        _keys.run_keys("add", ["ANTHROPIC_API_KEY"])

        monkeypatch.setattr(_system_mod, "secret_tool_lookup", lambda service, key: real_value)

        rc = _keys.run_keys("list", [])
        out = capsys.readouterr().out

        assert rc == 0
        assert "sk-a****bbbb" in out  # masked real value, not the empty index
        assert "✓" in out  # format badge computed against the real value, not ""

    def test_export_prints_the_real_value_from_the_keyring(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        real_value = "sk-ant-" + "b" * 40
        _home(tmp_path, monkeypatch)
        monkeypatch.setenv("DOCKET_SECRETS_BACKEND", "keyring")
        monkeypatch.setattr(_system_mod, "secret_tool_available", lambda: True)
        monkeypatch.setattr(_system_mod, "secret_tool_store", lambda *a, **k: True)
        monkeypatch.setattr(_keys._getpass, "getpass", lambda *a, **k: real_value)
        _keys.run_keys("add", ["ANTHROPIC_API_KEY"])

        monkeypatch.setattr(_system_mod, "secret_tool_lookup", lambda service, key: real_value)

        rc = _keys.run_keys("export", [])
        out = capsys.readouterr().out

        assert rc == 0
        assert f"export ANTHROPIC_API_KEY='{real_value}'" in out


# ── file backend is unaffected ───────────────────────────────────────────────────


class TestFileBackendUnaffected:
    def test_add_still_stores_the_real_value_in_secrets_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        monkeypatch.setattr(_keys._getpass, "getpass", lambda *a, **k: "sk-ant-realvalue0000000")

        rc = _keys.run_keys("add", ["ANTHROPIC_API_KEY"])

        assert rc == 0
        on_disk = json.loads(_secrets.SECRETS_FILE.read_text())
        assert on_disk["ANTHROPIC_API_KEY"] == "sk-ant-realvalue0000000"
