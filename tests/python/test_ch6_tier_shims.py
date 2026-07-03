"""CH-6 tests: tier/`profiles:` deprecation-shim removal (D-2 exit, 0.2.0).

Covers:
  - `docket profile <id> premium` (a tier name) now fails with a helpful
    model-id-based error, instead of silently resolving through the old
    TIER_ANCHORS table.
  - `docket models set <tier-name> <model>` and `docket tier` are rejected/removed.
  - the internal rank-anchor fallback chain still resolves (unchanged output).
  - the one-shot `profiles:` -> `roles:` registry migration: migrates once, is
    idempotent, leaves registries without the legacy key untouched, and leaves
    registries that already have `roles:` alone (flagged by `docket doctor` as
    a residual key instead of being silently overwritten).

All tests run `python -m docket` as a subprocess with OPENCLAW_DIR overridden
and DOCKET_NO_RESTART=1, mirroring tests/python/test_m4_wave1.py.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

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


def _make_env(oc_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        "OPENCLAW_DIR": str(oc_dir),
        "DOCKET_NO_RESTART": "1",
    }


def _setup_agent(tmp_path: Path, agent_id: str = "myshop") -> Path:
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir()
    ws = oc_dir / "workspaces" / "projects" / agent_id
    (ws / "memory").mkdir(parents=True)
    (ws / ".docket-meta.json").write_text(json.dumps(META))
    (ws / "SOUL.md").write_text("# SOUL\n")
    (oc_dir / "openclaw.json").write_text(json.dumps(OC_CONFIG))
    return oc_dir


def _run(args: list[str], oc_dir: Path) -> tuple[int, str, str]:
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "docket", *args],
        capture_output=True,
        text=True,
        env=_make_env(oc_dir),
    )
    return result.returncode, result.stdout, result.stderr


def _seed_registry(oc_dir: Path, reg: dict[str, Any]) -> Path:
    path = oc_dir / "docket-models.json"
    path.write_text(json.dumps(reg))
    return path


# ---------------------------------------------------------------------------
# Tier names are no longer accepted anywhere
# ---------------------------------------------------------------------------


class TestTierNamesRemoved:
    def test_profile_tier_name_fails_helpfully(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, err = _run(["profile", "myshop", "premium"], oc_dir)
        assert rc == 1
        assert "Invalid model" in err
        # Helpful, model-id-based guidance — not a silent tier -> anchor resolution.
        assert "provider/model" in err
        assert "docket models set" in err

    @pytest.mark.parametrize("tier", ["economy", "standard", "premium"])
    def test_models_set_tier_key_rejected(self, tier: str, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, err = _run(["models", "set", tier, "anthropic/claude-haiku-4-5"], oc_dir)
        assert rc == 1
        assert "Unknown key" in err

    def test_tier_command_removed(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["tier", "myshop"], oc_dir)
        assert rc == 1
        combined = out + err
        assert "removed" in combined.lower()
        assert "docket profile" in combined

    def test_completions_bash_no_longer_advertises_tier(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _err = _run(["completions", "bash"], oc_dir)
        assert rc == 0
        assert "tier" not in out

    def test_completions_zsh_no_longer_advertises_tier(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _err = _run(["completions", "zsh"], oc_dir)
        assert rc == 0
        assert "tier" not in out


# ---------------------------------------------------------------------------
# Fallback chain (internal rank anchors) still resolves
# ---------------------------------------------------------------------------


class TestFallbackChainPreserved:
    def test_models_list_shows_fallback_chain(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _err = _run(["models"], oc_dir)
        assert rc == 0
        assert "fallback" in out
        # premium -> standard -> economy anchors are still the built-in defaults.
        assert "claude-opus-4-6" in out
        assert "claude-sonnet-4-6" in out
        assert "claude-haiku-4-5" in out

    def test_preset_apply_still_resolves_roles(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, err = _run(["models", "preset", "openai"], oc_dir)
        assert rc == 0, err
        reg = json.loads((oc_dir / "docket-models.json").read_text())
        assert reg["roles"]["programmer"] == "openai/gpt-4.1-mini"
        # The retired tier.* registry keys are never written again.
        assert "profiles" not in reg


# ---------------------------------------------------------------------------
# Legacy `profiles:` -> `roles:` one-shot migration
# ---------------------------------------------------------------------------


class TestLegacyProfilesMigration:
    def test_migrates_once(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _seed_registry(
            oc_dir,
            {
                "profiles": {
                    "economy": "openai/gpt-4.1-nano",
                    "standard": "openai/gpt-4.1-mini",
                    "premium": "openai/gpt-4.1",
                }
            },
        )
        rc, out, err = _run(["models"], oc_dir)
        assert rc == 0, err
        combined = out + err
        assert "Migrated legacy" in combined

        reg = json.loads((oc_dir / "docket-models.json").read_text())
        assert "profiles" not in reg
        assert reg["roles"]["programmer"] == "openai/gpt-4.1-mini"  # strong class -> standard
        assert reg["roles"]["manager"] == "openai/gpt-4.1-nano"  # cheap class -> economy

    def test_idempotent_on_rerun(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _seed_registry(
            oc_dir,
            {"profiles": {"economy": "openai/gpt-4.1-nano", "standard": "openai/gpt-4.1-mini"}},
        )
        rc0, _out0, err0 = _run(["models"], oc_dir)
        assert rc0 == 0, err0
        reg_after_first = json.loads((oc_dir / "docket-models.json").read_text())

        rc, out, err = _run(["models"], oc_dir)
        assert rc == 0, err
        combined = out + err
        assert "Migrated legacy" not in combined  # second run: already migrated, silent

        reg_after_second = json.loads((oc_dir / "docket-models.json").read_text())
        assert reg_after_second == reg_after_first

    def test_registry_without_legacy_key_untouched(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        original = {
            "roles": {"programmer": "anthropic/claude-opus-4-6"},
            "default": "anthropic/claude-sonnet-4-6",
        }
        _seed_registry(oc_dir, original)

        rc, out, err = _run(["models"], oc_dir)
        assert rc == 0, err
        combined = out + err
        assert "Migrated legacy" not in combined

        reg = json.loads((oc_dir / "docket-models.json").read_text())
        assert reg == original

    def test_roles_already_present_leaves_profiles_for_doctor(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        original = {
            "profiles": {"economy": "openai/gpt-4.1-nano"},
            "roles": {"programmer": "anthropic/claude-opus-4-6"},
        }
        _seed_registry(oc_dir, original)

        rc, out, err = _run(["models"], oc_dir)
        assert rc == 0, err
        combined = out + err
        assert "Migrated legacy" not in combined

        reg = json.loads((oc_dir / "docket-models.json").read_text())
        assert reg == original  # left untouched — doctor flags this as residual

    def test_doctor_flags_residual_profiles_key(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _seed_registry(
            oc_dir,
            {
                "profiles": {"economy": "openai/gpt-4.1-nano"},
                "roles": {"programmer": "anthropic/claude-opus-4-6"},
            },
        )
        _rc, out, err = _run(["doctor"], oc_dir)
        combined = out + err
        assert "Residual 'profiles:' key" in combined

    def test_doctor_does_not_flag_clean_registry(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _seed_registry(oc_dir, {"roles": {"programmer": "anthropic/claude-opus-4-6"}})
        _rc, out, err = _run(["doctor"], oc_dir)
        combined = out + err
        assert "Residual 'profiles:' key" not in combined
        assert "No legacy 'profiles:' key" in combined

    def test_doctor_json_reports_model_registry(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _seed_registry(
            oc_dir,
            {"profiles": {"economy": "openai/gpt-4.1-nano", "standard": "openai/gpt-4.1-mini"}},
        )
        _rc, out, _err = _run(["doctor", "--json"], oc_dir)
        payload = json.loads(out)
        mr = payload["checks"]["modelRegistry"]
        assert mr["migrated"] is not None
        assert mr["residualProfilesKey"] is False
