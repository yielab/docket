"""`docket setup provider` credentials -- no per-agent file propagation, and the keyring backend actually
stores (not just looks up).

Nothing on the live turn path reads a per-agent file for credentials --
`models/adapters/openai_http.py` resolves them through `governance/secrets.py` directly, so
credentials are written nowhere else. Under `DOCKET_SECRETS_BACKEND=keyring`, add/rotate store
through `secret-tool store` and fail closed (never falling back to plaintext) if that
fails; remove clears the keyring entry too.
"""

from __future__ import annotations

import getpass
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from typer.testing import CliRunner

from docket.interfaces.cli.app import app
from docket.interfaces.cli.commands import setup_model_credentials as _setup_model_credentials
from docket.kernel.home import Home, current_home, use_home
from docket.platform import process as _process

SUBJECT = "docket.interfaces.cli.commands.setup_model_credentials"

_runner = CliRunner()


@contextmanager
def _home(
    tmp_path: Path,
) -> Iterator[Path]:
    home = tmp_path / ".docket"
    with use_home(Home(home)):
        yield home


def _add(name: str, value: str) -> bool:
    return _setup_model_credentials._write_credential(name, value, "add")


def _seed_workspace(home: Path, agent_id: str = "demo") -> Path:
    ws = home / "workspaces" / "projects" / agent_id
    ws.mkdir(parents=True)
    (ws / ".docket-meta.json").write_text('{"model": "anthropic/claude-sonnet-4-6"}')
    return ws


# ── no per-agent .env propagation ────────────────────────────────────────────────


class TestNoEnvSync:
    def test_credential_write_creates_no_env_in_any_workspace(self, tmp_path: Path) -> None:
        with _home(tmp_path) as home:
            ws = _seed_workspace(home)

            stored = _setup_model_credentials._write_credential(
                "ANTHROPIC_API_KEY", "fake-ant-testvalue00000000000000", "add"
            )

            assert stored is True
            assert not (ws / ".env").exists()
            assert list(ws.iterdir()) == [ws / ".docket-meta.json"]

    def test_credential_rotate_creates_no_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _home(tmp_path) as home:
            ws = _seed_workspace(home)
            _add("ANTHROPIC_API_KEY", "fake-ant-firstvalue000000")

            monkeypatch.setattr(getpass, "getpass", lambda *a, **k: "fake-ant-secondvalue00000")
            rc = _setup_model_credentials.credential_rotate("ANTHROPIC_API_KEY")

            assert rc == 0
            assert not (ws / ".env").exists()

    def test_credential_remove_creates_no_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _home(tmp_path) as home:
            ws = _seed_workspace(home)
            _add("ANTHROPIC_API_KEY", "fake-ant-testvalue00000000000000")
            monkeypatch.setattr("sys.stdin.isatty", lambda: False)

            rc = _setup_model_credentials.credential_remove("ANTHROPIC_API_KEY")

            assert rc == 0
            assert not (ws / ".env").exists()


# ── keyring backend: add/rotate actually store, not just look up ────────────────


class TestKeyringBackendStores:
    def test_add_stores_through_secret_tool_not_secrets_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _home(tmp_path):
            monkeypatch.setenv("DOCKET_SECRETS_BACKEND", "keyring")
            monkeypatch.setattr(_process, "secret_tool_available", lambda: True)
            stored: dict[str, str] = {}
            monkeypatch.setattr(
                _process,
                "secret_tool_store",
                lambda service, key, value: stored.setdefault(key, value) or True,
            )
            ok = _add("ANTHROPIC_API_KEY", "fake-ant-realvalue0000000")

            assert ok is True
            assert stored == {"ANTHROPIC_API_KEY": "fake-ant-realvalue0000000"}
            on_disk = json.loads(current_home().secrets_file.read_text())
            assert on_disk["ANTHROPIC_API_KEY"] == ""

    def test_add_fails_closed_when_secret_tool_store_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _home(tmp_path):
            monkeypatch.setenv("DOCKET_SECRETS_BACKEND", "keyring")
            monkeypatch.setattr(_process, "secret_tool_available", lambda: True)
            monkeypatch.setattr(_process, "secret_tool_store", lambda *a, **k: False)
            ok = _add("ANTHROPIC_API_KEY", "fake-ant-realvalue0000000")

            assert ok is False
            assert (
                not current_home().secrets_file.exists()
                or "ANTHROPIC_API_KEY"
                not in json.loads(current_home().secrets_file.read_text() or "{}")
            )

    def test_rotate_stores_through_secret_tool(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _home(tmp_path):
            # First add under the file backend so the key exists to rotate.
            _add("ANTHROPIC_API_KEY", "fake-ant-original00000000")

            monkeypatch.setenv("DOCKET_SECRETS_BACKEND", "keyring")
            monkeypatch.setattr(_process, "secret_tool_available", lambda: True)
            stored: dict[str, str] = {}
            monkeypatch.setattr(
                _process,
                "secret_tool_store",
                lambda service, key, value: stored.setdefault(key, value) or True,
            )
            monkeypatch.setattr(getpass, "getpass", lambda *a, **k: "fake-ant-rotated000000000")

            rc = _setup_model_credentials.credential_rotate("ANTHROPIC_API_KEY")

            assert rc == 0
            assert stored == {"ANTHROPIC_API_KEY": "fake-ant-rotated000000000"}
            on_disk = json.loads(current_home().secrets_file.read_text())
            assert on_disk["ANTHROPIC_API_KEY"] == ""

    def test_remove_clears_the_keyring_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _home(tmp_path):
            monkeypatch.setenv("DOCKET_SECRETS_BACKEND", "keyring")
            monkeypatch.setattr(_process, "secret_tool_available", lambda: True)
            monkeypatch.setattr(_process, "secret_tool_store", lambda *a, **k: True)
            _add("ANTHROPIC_API_KEY", "fake-ant-realvalue0000000")

            cleared: list[str] = []
            monkeypatch.setattr(
                _process, "secret_tool_clear", lambda service, key: cleared.append(key) or True
            )
            monkeypatch.setattr("sys.stdin.isatty", lambda: False)

            rc = _setup_model_credentials.credential_remove("ANTHROPIC_API_KEY")

            assert rc == 0
            assert cleared == ["ANTHROPIC_API_KEY"]
            assert "ANTHROPIC_API_KEY" not in json.loads(current_home().secrets_file.read_text())


def _reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    from docket.models.adapters import openai_http as _llm

    monkeypatch.setattr(_llm, "probe_models", lambda *a, **k: _llm.ProbeResult(status=200))


def _global_providers(home: Path) -> dict[str, dict[str, object]]:
    path = home / "docket-providers.json"
    if not path.exists():
        return {}
    providers: dict[str, dict[str, object]] = json.loads(path.read_text())["providers"]
    return providers


class TestKeyringRequestedWithoutSecretTool:
    @pytest.fixture(autouse=True)
    def _no_secret_tool(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        monkeypatch.setenv("DOCKET_SECRETS_BACKEND", "keyring")

    def test_a_credential_write_refuses_and_names_the_way_out(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _home(tmp_path):
            stored = _setup_model_credentials._write_credential(
                "ANTHROPIC_API_KEY", "sk-ant-secret1", "add"
            )

            assert stored is False
            assert not current_home().secrets_file.exists()
            err = capsys.readouterr().err
            assert "secret-tool" in err
            assert "DOCKET_SECRETS_BACKEND" in err

    def test_provider_add_refuses_before_probing_or_registering(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _home(tmp_path) as home:
            _reachable(monkeypatch)
            monkeypatch.delenv("UP_API_KEY", raising=False)

            result = _runner.invoke(
                app,
                [
                    "setup",
                    "provider",
                    "add",
                    "up",
                    "http://127.0.0.1:9/v1",
                    "--credential",
                    "sk-x1",
                ],
            )

            assert result.exit_code == 1
            assert "secret-tool" in result.stderr
            assert not current_home().secrets_file.exists()
            assert _global_providers(home) == {}

    def test_a_keyless_provider_does_not_need_the_keyring(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _home(tmp_path) as home:
            _reachable(monkeypatch)

            result = _runner.invoke(
                app, ["setup", "provider", "add", "free", "http://127.0.0.1:9/v1", "--no-preset"]
            )

            assert result.exit_code == 0, result.stdout + result.stderr
            assert "free" in _global_providers(home)
