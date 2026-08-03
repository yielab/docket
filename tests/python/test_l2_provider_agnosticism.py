"""Phase 18 L-2: finish provider agnosticism.

Covers the verified gaps left after Phase 6:
  - the internal rank-anchor seed table (`_RANK_ANCHORS`) is overridable from
    the user's docket-models.json, and a non-Anthropic preset leaves no
    Claude residue in `docket models`'s display
  - the "fallback" label was a false claim (nothing degrades to a cheaper
    model on failure) — it is now "rank anchors", with an honest caption
  - `docket auth login/key/setup` accept `--provider <name>` and thread it
    through to the ACL instead of hardcoding "anthropic"
  - a `local` preset exists and prices as "$0 (local)", never a fabricated
    dollar figure
  - unpriced models (including OpenRouter's non-curated routes) render an
    informative "n/a" variant, never "$0.00"
  - the two dead-end guidance strings in cli/_provider.py now name commands
    that actually exist

Unit-level tests import `docket.core.models_policy` directly; CLI-surface
tests run `python -m docket` as a subprocess, mirroring
tests/python/test_ch6_tier_shims.py.
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
# CLI-surface tests (subprocess), mirroring test_ch6_tier_shims.py
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

OC_CONFIG: dict[str, Any] = {
    "agents": {
        "defaults": {"model": ""},
        "list": [
            {
                "id": "myshop",
                "model": "anthropic/claude-sonnet-4-6",
                "metadata": {"sessionKey": "agent:myshop:default", "projectKey": "default"},
            }
        ],
    },
    "bindings": [],
    "security": {"gates": {"enabled": False}, "isolation": {"enabled": False}},
}


def _make_env(oc_dir: Path, extra_path: Path | None = None) -> dict[str, str]:
    env = {
        **os.environ,
        "OPENCLAW_DIR": str(oc_dir),
        "DOCKET_HOME": str(oc_dir),
        "DOCKET_NO_RESTART": "1",
    }
    if extra_path is not None:
        env["PATH"] = f"{extra_path}{os.pathsep}{env['PATH']}"
    return env


def _setup_agent(tmp_path: Path, agent_id: str = "myshop") -> Path:
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir()
    ws = oc_dir / "workspaces" / "projects" / agent_id
    (ws / "memory").mkdir(parents=True)
    (ws / ".docket-meta.json").write_text(json.dumps(META))
    (ws / "SOUL.md").write_text("# SOUL\n")
    (oc_dir / "openclaw.json").write_text(json.dumps(OC_CONFIG))
    return oc_dir


def _run(args: list[str], oc_dir: Path, extra_path: Path | None = None) -> tuple[int, str, str]:
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "docket", *args],
        capture_output=True,
        text=True,
        env=_make_env(oc_dir, extra_path),
    )
    return result.returncode, result.stdout, result.stderr


class TestNonAnthropicPresetShowsNoResidue:
    def test_openai_preset_then_models_has_no_claude_residue(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, err = _run(["models", "preset", "openai"], oc_dir)
        assert rc == 0, err

        rc, out, err = _run(["models"], oc_dir)
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
        oc_dir = _setup_agent(tmp_path)
        rc, _out, err = _run(["models", "preset", "google"], oc_dir)
        assert rc == 0, err
        reg = json.loads((oc_dir / "docket-models.json").read_text())
        assert reg["rankAnchors"]["standard"] == "google/gemini-2.5-flash"


class TestLocalPresetCli:
    def test_local_preset_listed(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["models", "preset"], oc_dir)
        assert rc == 0, err
        assert "local" in out

    def test_local_preset_applies_and_prices_zero(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, err = _run(["models", "preset", "local"], oc_dir)
        assert rc == 0, err

        rc, out, err = _run(["models"], oc_dir)
        assert rc == 0, err
        assert "$0 (local)" in out
        assert "n/a" not in out
        assert "$0.00" not in out


class TestAuthProviderFlag:
    """`docket auth login/key/setup --provider <x>` threads through to the ACL.

    A fake `openclaw` shim echoes back its own argv (as `AUTH_ARGS:<json>`) so
    the test can assert the exact command docket built, without a real
    daemon.
    """

    @staticmethod
    def _write_argv_echo_openclaw(bindir: Path) -> None:
        bindir.mkdir(parents=True, exist_ok=True)
        script = bindir / "openclaw"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import sys, json\n"
            "args = sys.argv[1:]\n"
            "if args[:1] == ['--version']:\n"
            "    print('openclaw 2026.2.23 (test shim)')\n"
            "else:\n"
            "    print('AUTH_ARGS:' + json.dumps(args))\n"
            "sys.exit(0)\n"
        )
        script.chmod(0o755)

    def _argv_from_output(self, out: str) -> list[str]:
        for line in out.splitlines():
            if line.startswith("AUTH_ARGS:"):
                result: list[str] = json.loads(line[len("AUTH_ARGS:") :])
                return result
        raise AssertionError(f"no AUTH_ARGS marker in output:\n{out}")

    def test_login_defaults_to_anthropic(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        bindir = tmp_path / "_ocbin"
        self._write_argv_echo_openclaw(bindir)
        rc, out, err = _run(["auth", "login"], oc_dir, extra_path=bindir)
        assert rc == 0, err
        argv = self._argv_from_output(out)
        assert argv == ["models", "auth", "setup-token", "--provider", "anthropic"]

    def test_login_threads_explicit_provider(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        bindir = tmp_path / "_ocbin"
        self._write_argv_echo_openclaw(bindir)
        rc, out, err = _run(["auth", "login", "--provider", "openai"], oc_dir, extra_path=bindir)
        assert rc == 0, err
        argv = self._argv_from_output(out)
        assert argv == ["models", "auth", "setup-token", "--provider", "openai"]

    def test_key_threads_explicit_provider(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        bindir = tmp_path / "_ocbin"
        self._write_argv_echo_openclaw(bindir)
        rc, out, err = _run(["auth", "key", "--provider", "openrouter"], oc_dir, extra_path=bindir)
        assert rc == 0, err
        argv = self._argv_from_output(out)
        assert argv == ["models", "auth", "paste-token", "--provider", "openrouter"]

    def test_provider_flag_not_duplicated_onto_extra(self, tmp_path: Path) -> None:
        """--provider must be consumed, not forwarded again as a stray extra."""
        oc_dir = _setup_agent(tmp_path)
        bindir = tmp_path / "_ocbin"
        self._write_argv_echo_openclaw(bindir)
        rc, out, err = _run(["auth", "login", "--provider", "google"], oc_dir, extra_path=bindir)
        assert rc == 0, err
        argv = self._argv_from_output(out)
        assert argv.count("--provider") == 1


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

    def test_no_raw_openclaw_command_emitted(self, capsys: pytest.CaptureFixture[str]) -> None:
        from docket.cli import _provider as _prov_cli

        _prov_cli._print_role_split("local", "qwen3-30b-a3b")
        out = capsys.readouterr().out
        assert "openclaw models status" not in out
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
