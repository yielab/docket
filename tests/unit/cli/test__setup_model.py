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


def _add(name: str, value: str) -> bool:
    return _setup_model._write_credential(name, value, "add")


def _seed_workspace(home: Path, agent_id: str = "demo") -> Path:
    ws = home / "workspaces" / "projects" / agent_id
    ws.mkdir(parents=True)
    (ws / ".docket-meta.json").write_text('{"model": "anthropic/claude-sonnet-4-6"}')
    return ws


# ── no per-agent .env propagation ────────────────────────────────────────────────


class TestNoEnvSync:
    def test_credential_write_creates_no_env_in_any_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        ws = _seed_workspace(home)

        stored = _setup_model._write_credential(
            "ANTHROPIC_API_KEY", "fake-ant-testvalue00000000000000", "add"
        )

        assert stored is True
        assert not (ws / ".env").exists()
        assert list(ws.iterdir()) == [ws / ".docket-meta.json"]

    def test_credential_rotate_creates_no_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        ws = _seed_workspace(home)
        _add("ANTHROPIC_API_KEY", "fake-ant-firstvalue000000")

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
        _add("ANTHROPIC_API_KEY", "fake-ant-testvalue00000000000000")
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
        ok = _add("ANTHROPIC_API_KEY", "fake-ant-realvalue0000000")

        assert ok is True
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
        ok = _add("ANTHROPIC_API_KEY", "fake-ant-realvalue0000000")

        assert ok is False
        assert not _secrets.SECRETS_FILE.exists() or "ANTHROPIC_API_KEY" not in json.loads(
            _secrets.SECRETS_FILE.read_text() or "{}"
        )

    def test_rotate_stores_through_secret_tool(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        # First add under the file backend so the key exists to rotate.
        _add("ANTHROPIC_API_KEY", "fake-ant-original00000000")

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
        _add("ANTHROPIC_API_KEY", "fake-ant-realvalue0000000")

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
        stored = _add("ANTHROPIC_API_KEY", "fake-ant-realvalue0000000")

        assert stored is True
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

    def test_a_preset_names_the_pods_and_roles_it_moved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        self._reachable(monkeypatch)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        ws = home / "workspaces" / "projects" / "shop-implementer"
        ws.mkdir(parents=True)
        (ws / ".docket-meta.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "kind": "project",
                    "scope": "project",
                    "role": "implementer",
                    "pod": "shop",
                    "model": "local/local-model",
                }
            )
        )

        result = _runner.invoke(
            app, ["setup", "provider", "add", "anthropic", "--credential", "fake-ant-" + "x" * 40]
        )

        assert result.exit_code == 0, result.stdout + result.stderr
        out = " ".join(result.output.split())
        assert "pod shop: implementer local/local-model -> anthropic/" in out
        assert "--no-preset" in out

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


class TestProviderLimits:
    @staticmethod
    def _probe(monkeypatch: pytest.MonkeyPatch, **limits: tuple[int | None, int | None]) -> None:
        from docket.core.llm import ModelLimits
        from docket.edges.adapters import llm as _llm

        monkeypatch.setattr(
            _llm,
            "probe_models",
            lambda *a, **k: _llm.ProbeResult(
                status=200,
                model_ids=sorted(limits),
                limits={m: ModelLimits(*pair) for m, pair in limits.items()},
            ),
        )

    def test_add_without_ctx_records_the_observed_window_and_declares_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        self._probe(monkeypatch, m=(32768, None))

        result = _runner.invoke(
            app, ["setup", "provider", "add", "custom", "http://127.0.0.1:1/v1", "--model", "m"]
        )

        assert result.exit_code == 0, result.stdout + result.stderr
        spec = _prov.load_catalog().get("custom")
        assert spec is not None
        assert (spec.models[0].context_window, spec.models[0].max_tokens) == (None, None)
        found = _prov.resolve_limits(spec, "m")
        assert (found.context_window, found.context_window_source) == (32768, "observed")
        assert (found.max_output, found.max_output_source) == (None, "unknown")

    def test_a_given_ctx_is_declared_and_wins_over_the_probe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        self._probe(monkeypatch, m=(32768, 9000))

        argv = ["setup", "provider", "add", "custom", "http://127.0.0.1:1/v1"]
        result = _runner.invoke(app, [*argv, "--model", "m", "--ctx", "1000"])

        assert result.exit_code == 0, result.stdout + result.stderr
        spec = _prov.load_catalog().get("custom")
        assert spec is not None
        found = _prov.resolve_limits(spec, "m")
        assert (found.context_window, found.context_window_source) == (1000, "declared")
        assert (found.max_output, found.max_output_source) == (9000, "observed")

    def test_show_prints_each_limit_with_its_source(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        spec = _prov.ProviderSpec(
            name="gw",
            baseUrl="http://127.0.0.1:1/v1",
            auth=_prov.AuthSpec(type="none"),
            models=[
                _prov.ModelRow(id="declared", contextWindow=1000, maxTokens=500),
                _prov.ModelRow(id="seen"),
                _prov.ModelRow(id="blank"),
            ],
        )
        _prov.save_provider(spec)
        from docket.core.llm import ModelLimits
        from docket.edges.adapters.llm import ProbeResult

        _prov.record_observed_models(
            spec,
            ProbeResult(status=200, model_ids=["seen"], limits={"seen": ModelLimits(32768, None)}),
        )
        when = _prov.observed_at("gw")

        result = _runner.invoke(app, ["setup", "provider", "show", "gw"])

        assert result.exit_code == 0, result.stdout + result.stderr
        rows = {
            line.split()[0]: " ".join(line.split()[1:])
            for line in result.stdout.splitlines()
            if line.split()[:1] in (["declared"], ["seen"], ["blank"])
        }
        assert rows["declared"] == "1000 (declared) 500 (declared)"
        assert rows["seen"] == f"32768 (observed {when}) unknown"
        assert rows["blank"] == "unknown unknown"

    def test_show_json_carries_the_resolved_limits_and_sources(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        spec = _prov.ProviderSpec(
            name="gw",
            baseUrl="http://127.0.0.1:1/v1",
            auth=_prov.AuthSpec(type="none"),
            models=[_prov.ModelRow(id="seen"), _prov.ModelRow(id="blank")],
        )
        _prov.save_provider(spec)
        from docket.core.llm import ModelLimits
        from docket.edges.adapters.llm import ProbeResult

        _prov.record_observed_models(
            spec,
            ProbeResult(status=200, model_ids=["seen"], limits={"seen": ModelLimits(32768, 4096)}),
        )

        result = _runner.invoke(app, ["setup", "provider", "show", "gw", "--json"])

        assert result.exit_code == 0, result.stdout + result.stderr
        seen, blank = json.loads(result.stdout)["models"]
        assert seen["contextWindow"] == 32768 and seen["maxTokens"] == 4096
        assert seen["limitsSource"] == "observed" and seen["observedAt"] == _prov.observed_at("gw")
        assert (blank["contextWindow"], blank["maxTokens"]) == (None, None)
        assert blank["limitsSource"] == "unknown"
        assert blank["observedAt"] == ""

    def test_a_built_in_model_nobody_observed_is_unknown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        result = _runner.invoke(app, ["setup", "provider", "show", "anthropic", "--json"])
        assert result.exit_code == 0, result.stdout + result.stderr
        models = json.loads(result.stdout)["models"]
        assert models and all(m["limitsSource"] == "unknown" for m in models)
        assert all(m["contextWindow"] is None and m["maxTokens"] is None for m in models)


def _reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    from docket.edges.adapters import llm as _llm

    monkeypatch.setattr(_llm, "probe_models", lambda *a, **k: _llm.ProbeResult(status=200))


def _global_providers(home: Path) -> dict[str, dict[str, object]]:
    path = home / "docket-providers.json"
    if not path.exists():
        return {}
    providers: dict[str, dict[str, object]] = json.loads(path.read_text())["providers"]
    return providers


class TestProviderAddRefusesMissingRankAnchors:
    def test_an_anthropic_document_without_presets_is_refused_and_stores_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        _reachable(monkeypatch)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        doc = tmp_path / "anthropic.yaml"
        doc.write_text(
            "kind: provider\nname: anthropic\nbaseUrl: https://api.anthropic.com/v1\n"
            "auth: {type: bearer, credentials: [ANTHROPIC_API_KEY]}\npresets: []\n"
        )

        result = _runner.invoke(
            app, ["setup", "provider", "add", str(doc), "--credential", "sk-ant-" + "x" * 20]
        )

        assert result.exit_code == 1
        assert "economy" in result.stderr
        assert _global_providers(home) == {}
        assert _secrets.load_secrets() == {}


class TestProviderAddStoresNothingOnTransportFailure:
    def test_an_unreachable_endpoint_leaves_no_credential_behind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        monkeypatch.delenv("DOWN_API_KEY", raising=False)

        result = _runner.invoke(
            app,
            ["setup", "provider", "add", "down", "http://127.0.0.1:9/v1", "--credential", "sk-x1"],
        )

        assert result.exit_code == 1
        assert "Nothing was registered" in result.stderr
        assert _secrets.load_secrets() == {}
        assert not _secrets.SECRETS_META_FILE.exists()
        assert _global_providers(home) == {}

    def test_a_reachable_endpoint_stores_the_credential_after_the_probe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.edges.adapters import llm as _llm

        _home(tmp_path, monkeypatch)
        monkeypatch.delenv("UP_API_KEY", raising=False)
        seen: list[str] = []

        def probe(endpoint: object, *a: object, **k: object) -> _llm.ProbeResult:
            seen.append(getattr(endpoint, "api_key", ""))
            assert _secrets.load_secrets() == {}
            return _llm.ProbeResult(status=200)

        monkeypatch.setattr(_llm, "probe_models", probe)

        result = _runner.invoke(
            app,
            ["setup", "provider", "add", "up", "http://127.0.0.1:9/v1", "--credential", "sk-x1"],
        )

        assert result.exit_code == 0, result.stdout + result.stderr
        assert seen == ["sk-x1"]
        assert _secrets.load_secrets() == {"UP_API_KEY": "sk-x1"}

    def test_a_rejected_credential_is_reported_as_rejected_not_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.edges.adapters import llm as _llm

        _home(tmp_path, monkeypatch)
        monkeypatch.delenv("UP_API_KEY", raising=False)
        monkeypatch.setattr(_llm, "probe_models", lambda *a, **k: _llm.ProbeResult(status=401))

        result = _runner.invoke(
            app,
            ["setup", "provider", "add", "up", "http://127.0.0.1:9/v1", "--credential", "sk-x1"],
        )

        assert result.exit_code == 0, result.stdout + result.stderr
        assert "was rejected (HTTP 401)" in " ".join(result.output.split())


class TestKeyringRequestedWithoutSecretTool:
    @pytest.fixture(autouse=True)
    def _no_secret_tool(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        monkeypatch.setenv("DOCKET_SECRETS_BACKEND", "keyring")

    def test_a_credential_write_refuses_and_names_the_way_out(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _home(tmp_path, monkeypatch)

        stored = _setup_model._write_credential("ANTHROPIC_API_KEY", "sk-ant-secret1", "add")

        assert stored is False
        assert not _secrets.SECRETS_FILE.exists()
        err = capsys.readouterr().err
        assert "secret-tool" in err
        assert "DOCKET_SECRETS_BACKEND" in err

    def test_provider_add_refuses_before_probing_or_registering(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        _reachable(monkeypatch)
        monkeypatch.delenv("UP_API_KEY", raising=False)

        result = _runner.invoke(
            app,
            ["setup", "provider", "add", "up", "http://127.0.0.1:9/v1", "--credential", "sk-x1"],
        )

        assert result.exit_code == 1
        assert "secret-tool" in result.stderr
        assert not _secrets.SECRETS_FILE.exists()
        assert _global_providers(home) == {}

    def test_a_keyless_provider_does_not_need_the_keyring(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        _reachable(monkeypatch)

        result = _runner.invoke(
            app, ["setup", "provider", "add", "free", "http://127.0.0.1:9/v1", "--no-preset"]
        )

        assert result.exit_code == 0, result.stdout + result.stderr
        assert "free" in _global_providers(home)


class TestProviderAddLimitsKeepInheritedRows:
    @staticmethod
    def _builtin_rows(name: str) -> list[_prov.ModelRow]:
        spec = _prov.load_catalog().get(name)
        assert spec is not None
        return list(spec.models)

    def test_ctx_without_a_model_on_a_multi_row_provider_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        _reachable(monkeypatch)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        result = _runner.invoke(
            app,
            ["setup", "provider", "add", "anthropic", "--credential", "sk-ant-x", "--ctx", "1000"],
        )

        assert result.exit_code == 1
        assert "--model" in result.stderr
        assert _global_providers(home) == {}
        assert _secrets.load_secrets() == {}

    def test_ctx_on_a_provider_with_no_rows_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        _reachable(monkeypatch)

        result = _runner.invoke(app, ["setup", "provider", "add", "local", "--max-tokens", "512"])

        assert result.exit_code == 1
        assert "--model" in result.stderr
        assert _global_providers(home) == {}

    def test_ctx_with_a_known_model_changes_only_that_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        _reachable(monkeypatch)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        before = self._builtin_rows("anthropic")

        result = _runner.invoke(
            app,
            [
                *("setup", "provider", "add", "anthropic", "--credential", "sk-ant-x"),
                *("--model", "claude-haiku-4-5", "--ctx", "1000", "--max-tokens", "500"),
                "--no-preset",
            ],
        )

        assert result.exit_code == 0, result.stdout + result.stderr
        after = _prov.load_catalog().get("anthropic")
        assert after is not None
        assert [row.id for row in after.models] == [row.id for row in before]
        by_id = {row.id: row for row in after.models}
        assert (by_id["claude-haiku-4-5"].context_window, by_id["claude-haiku-4-5"].max_tokens) == (
            1000,
            500,
        )
        for original in before:
            assert by_id[original.id].price == original.price
        assert after.headers == {"anthropic-version": "2023-06-01"}

    def test_a_url_over_a_built_in_keeps_every_row_and_its_price(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        _reachable(monkeypatch)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        before = self._builtin_rows("anthropic")

        result = _runner.invoke(
            app,
            [
                *("setup", "provider", "add", "anthropic", "http://127.0.0.1:9/v1"),
                *("--credential", "sk-ant-x", "--no-preset"),
            ],
        )

        assert result.exit_code == 0, result.stdout + result.stderr
        after = _prov.load_catalog().get("anthropic")
        assert after is not None
        assert after.base_url == "http://127.0.0.1:9/v1"
        assert after.models == before

    def test_an_unlisted_model_over_a_built_in_adds_a_row_beside_the_inherited_ones(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        _reachable(monkeypatch)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        before = self._builtin_rows("anthropic")

        result = _runner.invoke(
            app,
            [
                *("setup", "provider", "add", "anthropic", "--credential", "sk-ant-x"),
                *("--model", "claude-new", "--ctx", "2000", "--no-preset"),
            ],
        )

        assert result.exit_code == 0, result.stdout + result.stderr
        after = _prov.load_catalog().get("anthropic")
        assert after is not None
        assert after.models[: len(before)] == before
        assert [(r.id, r.context_window) for r in after.models[len(before) :]] == [
            ("claude-new", 2000)
        ]

    def test_ctx_alone_applies_to_the_only_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        _reachable(monkeypatch)
        _prov.save_provider(
            _prov.ProviderSpec(
                name="solo",
                baseUrl="http://127.0.0.1:9/v1",
                auth=_prov.AuthSpec(type="none"),
                models=[_prov.ModelRow(id="only")],
            )
        )

        result = _runner.invoke(app, ["setup", "provider", "add", "solo", "--ctx", "777"])

        assert result.exit_code == 0, result.stdout + result.stderr
        after = _prov.load_catalog().get("solo")
        assert after is not None
        assert [(r.id, r.context_window) for r in after.models] == [("only", 777)]
