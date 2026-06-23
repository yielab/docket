"""M5 T5.6 tests: local provider registration (models provider add).

Port of scripts/wire-local-provider.sh. These call register_local_provider()
in-process with OPENCLAW_DIR repointed at a temp seed and the endpoint ping
monkeypatched (no real network). We assert the resulting models.providers block
matches the script's output, and that a re-run is a no-op.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.core import provider as _prov
from docket.edges.adapters import openclaw as _oc

# Minimal openclaw.json seed (no providers yet).
_OC_CONFIG: dict[str, Any] = {
    "agents": {"defaults": {"model": "anthropic/claude-sonnet-4-6"}, "list": []},
    "bindings": [],
    "security": {"gates": {"enabled": False}, "isolation": {"enabled": False}},
}


def _point_config_at(oc_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_file = oc_dir / "openclaw.json"
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir()
    cfg_file = oc_dir / "openclaw.json"
    cfg_file.write_text(json.dumps(_OC_CONFIG))
    cfg_file.chmod(0o600)
    _point_config_at(oc_dir, monkeypatch)
    # Default: ping fails (offline) so tests never hit the network.
    monkeypatch.setattr(_prov, "ping_endpoint", lambda *a, **k: False)
    return oc_dir


def _providers(oc_dir: Path) -> dict[str, Any]:
    cfg = json.loads((oc_dir / "openclaw.json").read_text())
    providers = cfg.get("models", {}).get("providers", {})
    assert isinstance(providers, dict)
    return providers


# ── ACL config shape: must match the script's PROVIDER_JSON exactly ────────────


def test_local_provider_config_matches_script() -> None:
    cfg = _oc.local_provider_config(
        "http://127.0.0.1:8080/v1", "qwen3-30b-a3b", "Qwen3 30B-A3B (local)", 16384, 8192
    )
    assert cfg == {
        "baseUrl": "http://127.0.0.1:8080/v1",
        "apiKey": "local",
        "api": "openai-completions",
        "models": [
            {
                "id": "qwen3-30b-a3b",
                "name": "Qwen3 30B-A3B (local)",
                "reasoning": False,
                "input": ["text"],
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                "contextWindow": 16384,
                "maxTokens": 8192,
            }
        ],
    }


# ── registration writes the expected block ─────────────────────────────────────


def test_register_writes_provider_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    oc_dir = _seed(tmp_path, monkeypatch)
    rc = _prov.register_local_provider()
    assert rc == 0

    providers = _providers(oc_dir)
    assert set(providers) == {"local"}
    assert providers["local"] == _oc.local_provider_config(
        _prov.DEFAULT_BASE_URL,
        _prov.DEFAULT_MODEL_ID,
        _prov.DEFAULT_MODEL_NAME,
        _prov.DEFAULT_CTX,
        _prov.DEFAULT_MAX_TOKENS,
    )

    out = capsys.readouterr().out
    # Role-split commands are printed as in the script.
    assert "docket models set programmer local/qwen3-30b-a3b" in out
    assert "docket models set manager    anthropic/claude-sonnet-4-6" in out


def test_register_custom_args(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    oc_dir = _seed(tmp_path, monkeypatch)
    rc = _prov.register_local_provider(
        name="lab",
        base_url="http://10.0.0.5:1234/v1",
        model_id="llama-3.3-70b",
        model_name="Llama 3.3 70B",
        ctx=32768,
        max_tokens=4096,
    )
    assert rc == 0
    entry = _providers(oc_dir)["lab"]
    assert entry["baseUrl"] == "http://10.0.0.5:1234/v1"
    assert entry["models"][0]["id"] == "llama-3.3-70b"
    assert entry["models"][0]["contextWindow"] == 32768
    assert entry["models"][0]["maxTokens"] == 4096


# ── idempotency ────────────────────────────────────────────────────────────────


def test_rerun_is_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    oc_dir = _seed(tmp_path, monkeypatch)
    assert _oc.add_local_provider("local", _prov.DEFAULT_BASE_URL, "q", "Q", 16384, 8192) is True
    # Mtime-independent check: the ACL reports no change on identical re-run.
    assert _oc.add_local_provider("local", _prov.DEFAULT_BASE_URL, "q", "Q", 16384, 8192) is False

    before = (oc_dir / "openclaw.json").read_text()
    _prov.register_local_provider(model_id="q", model_name="Q")
    capsys.readouterr()
    _prov.register_local_provider(model_id="q", model_name="Q")
    out = capsys.readouterr().out
    after = (oc_dir / "openclaw.json").read_text()
    assert before == after
    assert "no change" in out


def test_update_existing_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(tmp_path, monkeypatch)
    assert _oc.add_local_provider("local", "http://a/v1", "m", "M", 8192, 4096) is True
    # Changing the context window is a real change.
    assert _oc.add_local_provider("local", "http://a/v1", "m", "M", 16384, 4096) is True
    assert _oc.get_local_provider("local") is not None
    assert _oc.get_local_provider("local")["models"][0]["contextWindow"] == 16384  # type: ignore[index]


def test_ping_failure_is_non_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    oc_dir = _seed(tmp_path, monkeypatch)  # ping already stubbed to False
    rc = _prov.register_local_provider()
    assert rc == 0
    assert "local" in _providers(oc_dir)
    out = capsys.readouterr().out
    assert "Could not reach" in out  # warn() → stdout (mirrors Bash)


def test_other_config_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    oc_dir = _seed(tmp_path, monkeypatch)
    _prov.register_local_provider()
    cfg = json.loads((oc_dir / "openclaw.json").read_text())
    # Unrelated top-level keys survive the providers write.
    assert cfg["agents"]["defaults"]["model"] == "anthropic/claude-sonnet-4-6"
    assert cfg["security"]["gates"]["enabled"] is False
