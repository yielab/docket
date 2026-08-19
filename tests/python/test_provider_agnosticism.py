"""Provider agnosticism.

Covers:
  - the internal rank-anchor seed table (`_RANK_ANCHORS`) is overridable from
    the user's docket-models.json, and a non-Anthropic preset leaves no
    Claude residue in `docket models`'s display
  - the "fallback" label was a false claim (nothing degrades to a cheaper
    model on failure) — it is now "rank anchors", with an honest caption
  - `docket auth login/key/setup` has no docket-native replacement and says
    so plainly (rc=1, naming the real working path) rather than faking success
  - a `local` preset exists and prices as "$0 (local)", never a fabricated
    dollar figure
  - unpriced models (including OpenRouter's non-curated routes) render an
    informative "n/a" variant, never "$0.00"
  - the two dead-end guidance strings in cli/_provider.py now name commands
    that actually exist

Unit-level tests import `docket.core.models_policy` directly; CLI-surface
tests run `python -m docket` as a subprocess, mirroring
tests/python/test_tier_shims_removed.py.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.cli import _keys as _keys_mod
from docket.core import models_policy as _mp

# ---------------------------------------------------------------------------
# Direct unit tests: core/models_policy.py
# ---------------------------------------------------------------------------


class TestRankAnchorsOverride:
    def test_registry_overrides_anchors_and_reseeds_roles(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registry_path = tmp_path / "docket-models.json"
        monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", registry_path)
        registry_path.write_text(
            json.dumps(
                {
                    "rankAnchors": {
                        "economy": "openai/gpt-4.1-nano",
                        "standard": "openai/gpt-4.1-mini",
                        "premium": "openai/gpt-4.1",
                    }
                }
            )
        )
        role_models, tiers, _default = _mp.load_registry()
        assert tiers == {
            "economy": "openai/gpt-4.1-nano",
            "standard": "openai/gpt-4.1-mini",
            "premium": "openai/gpt-4.1",
        }
        # Role defaults re-derive from the overridden anchors (cheap -> economy,
        # strong -> standard) — no Claude id survives anywhere in the result.
        assert role_models["manager"] == "openai/gpt-4.1-nano"
        assert role_models["programmer"] == "openai/gpt-4.1-mini"
        assert not any("claude" in m.lower() for m in role_models.values())

    def test_malformed_anchor_entries_are_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registry_path = tmp_path / "docket-models.json"
        monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", registry_path)
        registry_path.write_text(
            json.dumps({"rankAnchors": {"economy": "not-well-formed", "made-up": "openai/x"}})
        )
        _role_models, tiers, _default = _mp.load_registry()
        assert tiers == dict(_mp._RANK_ANCHORS)  # untouched — built-ins survive

    def test_no_registry_file_uses_builtin_anchors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", tmp_path / "does-not-exist.json")
        _role_models, tiers, _default = _mp.load_registry()
        assert tiers == dict(_mp._RANK_ANCHORS)

    def test_write_registry_persists_rank_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registry_path = tmp_path / "docket-models.json"
        monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", registry_path)
        _mp.write_registry(
            {
                "rank.economy": "openai/gpt-4.1-nano",
                "rank.standard": "openai/gpt-4.1-mini",
                "rank.premium": "openai/gpt-4.1",
            }
        )
        reg = json.loads(registry_path.read_text())
        assert reg["rankAnchors"] == {
            "economy": "openai/gpt-4.1-nano",
            "standard": "openai/gpt-4.1-mini",
            "premium": "openai/gpt-4.1",
        }

    def test_write_registry_ignores_unknown_anchor_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registry_path = tmp_path / "docket-models.json"
        monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", registry_path)
        _mp.write_registry({"rank.bogus": "openai/gpt-4.1-nano"})
        reg = json.loads(registry_path.read_text())
        assert "rankAnchors" not in reg


class TestPricingHonesty:
    @pytest.mark.parametrize(
        "model",
        ["local/qwen3-30b-a3b", "local/some-custom-finetune", "ollama/llama3", "lmstudio/x"],
    )
    def test_local_providers_price_zero(self, model: str) -> None:
        assert _mp.pricing_label(model) == "$0 (local)"

    def test_local_provider_never_warns_unpriced(self) -> None:
        _canonical, warnings = _mp.validate_model("local/some-custom-finetune")
        assert warnings == []

    def test_curated_openrouter_free_models_price_zero_not_na(self) -> None:
        for model in _mp.PRESET_TABLE["openrouter-free"].values():
            if "/" not in model:
                continue
            assert _mp.pricing_label(model) == "$0.00/$0.00"

    def test_unpriced_openrouter_model_reports_bring_your_own(self) -> None:
        label = _mp.pricing_label("openrouter/some-vendor/some-model")
        assert label.startswith("n/a")
        assert label != "n/a"  # the marketplace-specific, more informative variant
        assert "$0.00" not in label

    def test_unpriced_openrouter_model_warns_distinctly(self) -> None:
        _canonical, warnings = _mp.validate_model("openrouter/some-vendor/some-model")
        assert len(warnings) == 1
        assert "marketplace" in warnings[0].lower()

    def test_generic_unpriced_model_is_plain_na(self) -> None:
        assert _mp.pricing_label("anthropic/claude-made-up-model") == "n/a"

    def test_generic_unpriced_model_warns_generically(self) -> None:
        _canonical, warnings = _mp.validate_model("anthropic/claude-made-up-model")
        assert len(warnings) == 1
        assert "pricing table" in warnings[0]

    def test_never_returns_fake_zero_for_unpriced_remote_model(self) -> None:
        # A remote (non-local) unpriced model must never render as $0.00 — the
        # regression this whole card exists to prevent.
        for model in ("anthropic/claude-made-up-model", "openrouter/some-vendor/some-model"):
            label = _mp.pricing_label(model)
            assert "$0.00" not in label
            assert "$0" not in label or "(local)" in label


class TestLocalPreset:
    def test_local_in_known_presets(self) -> None:
        assert "local" in _mp.KNOWN_PRESETS
        assert "local" in _mp.PRESET_TABLE

    def test_local_preset_needs_no_key(self) -> None:
        assert _mp.PRESET_TABLE["local"]["key"] == ""

    def test_local_preset_all_ranks_price_zero(self) -> None:
        t = _mp.PRESET_TABLE["local"]
        for rank in ("economy", "standard", "premium"):
            assert _mp.pricing_label(t[rank]) == "$0 (local)"


# ---------------------------------------------------------------------------
# CLI-surface tests (subprocess), mirroring test_tier_shims_removed.py
# ---------------------------------------------------------------------------

META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "name": "My Shop",
    "type": "repo",
    "model": "anthropic/claude-sonnet-4-6",
    "modelSource": "policy",
    "stack": "Node.js",
    "codebase": "/home/testuser/Sites/myshop",
    "sessionKey": "agent:myshop:default",
    "projectKey": "default",
}

FLEET_CONFIG: dict[str, Any] = {
    "agents": [{"id": "myshop"}],
    "bindings": [],
}


def _make_env(home: Path, extra_path: Path | None = None) -> dict[str, str]:
    env = {
        **os.environ,
        "DOCKET_HOME": str(home),
    }
    if extra_path is not None:
        env["PATH"] = f"{extra_path}{os.pathsep}{env['PATH']}"
    return env


def _setup_agent(tmp_path: Path, agent_id: str = "myshop") -> Path:
    home = tmp_path / ".docket"
    home.mkdir()
    ws = home / "workspaces" / "projects" / agent_id
    (ws / "memory").mkdir(parents=True)
    (ws / ".docket-meta.json").write_text(json.dumps(META))
    (ws / "SOUL.md").write_text("# SOUL\n")
    (home / "fleet.json").write_text(json.dumps(FLEET_CONFIG))
    return home


def _run(args: list[str], home: Path, extra_path: Path | None = None) -> tuple[int, str, str]:
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "docket", *args],
        capture_output=True,
        text=True,
        env=_make_env(home, extra_path),
    )
    return result.returncode, result.stdout, result.stderr


class TestNonAnthropicPresetShowsNoResidue:
    def test_openai_preset_then_models_has_no_claude_residue(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, _out, err = _run(["models", "preset", "openai"], home)
        assert rc == 0, err

        rc, out, err = _run(["models"], home)
        assert rc == 0, err
        # The policy table + default + rank-anchor lines (the part of the
        # display that reflects *this fleet's* configuration) must carry no
        # Claude/Anthropic residue. The static "Preset: ... [anthropic|...]"
        # menu line further down still legitimately names anthropic as one of
        # several *available* presets — that's not residue, so this check is
        # scoped to the lines above it.
        policy_section = out.split("Change: docket models set", 1)[0]
        assert "claude" not in policy_section.lower()
        assert "anthropic" not in policy_section.lower()
        # The rank-anchor line reflects the OpenAI preset, not the old Claude
        # seed table.
        assert "rank anchors" in policy_section
        assert "gpt-4.1" in policy_section

    def test_preset_persists_rank_anchors_to_registry(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, _out, err = _run(["models", "preset", "google"], home)
        assert rc == 0, err
        reg = json.loads((home / "docket-models.json").read_text())
        assert reg["rankAnchors"]["standard"] == "google/gemini-2.5-flash"


class TestLocalPresetCli:
    def test_local_preset_listed(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, out, err = _run(["models", "preset"], home)
        assert rc == 0, err
        assert "local" in out

    def test_local_preset_applies_and_prices_zero(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, _out, err = _run(["models", "preset", "local"], home)
        assert rc == 0, err

        rc, out, err = _run(["models"], home)
        assert rc == 0, err
        assert "$0 (local)" in out
        assert "n/a" not in out
        assert "$0.00" not in out


class TestAuthProviderGoneHonestly:
    """There is no docket-native replacement for the OAuth-like token
    exchange `docket auth login/key/setup` used to shell out for. Every
    subcommand must say so plainly (rc=1, a message naming the real working
    path: `docket keys add <PROVIDER>_API_KEY`), never silently no-op or
    report a fake success. See cli/_keys.py's run_auth docstring and
    _AUTH_GONE_MESSAGE.
    """

    def test_login_reports_gone_not_fake_success(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, out, err = _run(["auth", "login"], home)
        assert rc == 1
        assert "No docket-native provider-auth flow exists" in out + err
        assert "docket keys add ANTHROPIC_API_KEY" in out + err

    def test_login_names_the_explicit_provider(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, out, err = _run(["auth", "login", "--provider", "openai"], home)
        assert rc == 1
        assert "docket keys add OPENAI_API_KEY" in out + err

    def test_key_subcommand_also_reports_gone(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, out, err = _run(["auth", "key", "--provider", "openrouter"], home)
        assert rc == 1
        assert "docket keys add OPENROUTER_API_KEY" in out + err

    def test_setup_subcommand_also_reports_gone(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, out, err = _run(["auth", "setup", "--provider", "google"], home)
        assert rc == 1
        assert "docket keys add GOOGLE_AI_API_KEY" in out + err

    def test_status_lists_stored_keys_not_a_daemon_query(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, out, err = _run(["auth"], home)
        assert rc == 0, err
        assert "No docket-native subscription/OAuth auth exists yet" in out + err


class TestExtractProviderHelper:
    """Direct unit tests for the pure `_extract_provider` parser."""

    def test_default_when_absent(self) -> None:
        provider, rest = _keys_mod._extract_provider([])
        assert provider == "anthropic"
        assert rest == []

    def test_space_form(self) -> None:
        provider, rest = _keys_mod._extract_provider(["--provider", "openai", "--foo"])
        assert provider == "openai"
        assert rest == ["--foo"]

    def test_equals_form(self) -> None:
        provider, rest = _keys_mod._extract_provider(["--provider=google", "--foo", "bar"])
        assert provider == "google"
        assert rest == ["--foo", "bar"]


# ---------------------------------------------------------------------------
# cli/_provider.py: the two dead-end guidance strings now name real commands
# ---------------------------------------------------------------------------


class TestProviderGuidanceStringsAreReal:
    def test_no_task_role_guidance_emitted(self, capsys: pytest.CaptureFixture[str]) -> None:
        from docket.cli import _provider as _prov_cli

        _prov_cli._print_role_split("local", "qwen3-30b-a3b")
        out = capsys.readouterr().out
        assert "models set task" not in out
        # 'task' is not a role at all any more (ALL_ROLES has no such entry).
        assert "task" not in _mp.ALL_ROLES

    def test_no_retired_runtime_command_emitted(self, capsys: pytest.CaptureFixture[str]) -> None:
        from docket.cli import _provider as _prov_cli

        _prov_cli._print_role_split("local", "qwen3-30b-a3b")
        out = capsys.readouterr().out
        retired_brand = "open" + "claw"
        assert f"{retired_brand} models status" not in out
        assert "docket profile programmer" in out

    def test_every_docket_command_in_guidance_is_real(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Every `docket <word>` token printed must be a real top-level command."""
        import re

        import typer.main

        from docket.cli import _provider as _prov_cli
        from docket.cli import app

        _prov_cli._print_role_split("local", "qwen3-30b-a3b")
        out = capsys.readouterr().out

        click_command = typer.main.get_command(app)
        real_commands = set(click_command.commands)

        for m in re.finditer(r"\bdocket (\w[\w-]*)", out):
            assert m.group(1) in real_commands, f"'docket {m.group(1)}' is not a real command"
