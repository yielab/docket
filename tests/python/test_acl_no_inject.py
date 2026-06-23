"""Regression: the ACL must never inject modeled-but-empty keys on write.

OpenClaw rejects unrecognised keys and refuses to start. An earlier bug dumped
the Pydantic models with their default `metadata` / `security` objects, so any
config write (e.g. `docket models set`) added `metadata: {sessionKey:"",
projectKey:""}` to every agent and a default root `security` block — which
crash-looped the gateway. Writes must preserve unknown keys but add nothing.
"""

import importlib
import json
from pathlib import Path

import pytest


def _load_acl(oc_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENCLAW_DIR", str(oc_dir))
    import docket.config as cfg

    importlib.reload(cfg)
    import docket.edges.adapters.openclaw as oc

    importlib.reload(oc)
    return oc


def test_set_model_does_not_inject_metadata_or_security(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir()
    config = {
        "agents": {
            "defaults": {"model": "anthropic/claude-sonnet-4-6"},
            "list": [
                {"id": "main", "model": "anthropic/claude-sonnet-4-6"},
                {"id": "shop", "model": "anthropic/claude-sonnet-4-6"},
            ],
        },
        "bindings": [{"agentId": "shop", "match": {"channel": "telegram", "peer": {"id": "-100"}}}],
        # Unknown-to-docket keys that MUST survive the round-trip.
        "channels": {"telegram": {"enabled": True, "botToken": "secret", "streaming": True}},
    }
    (oc_dir / "openclaw.json").write_text(json.dumps(config))

    oc = _load_acl(oc_dir, monkeypatch)
    oc.set_agent_model("shop", "local/qwen3-30b-a3b")

    out = json.loads((oc_dir / "openclaw.json").read_text())
    agents = out["agents"]["list"]

    # The bug: every agent gained an empty `metadata` and the root gained `security`.
    assert all("metadata" not in a for a in agents), "metadata must not be injected"
    assert "security" not in out, "default security block must not be injected"
    # Unknown keys preserved.
    assert out["channels"]["telegram"]["botToken"] == "secret"
    assert out["channels"]["telegram"]["streaming"] is True
    # The intended change applied.
    assert next(a for a in agents if a["id"] == "shop")["model"] == "local/qwen3-30b-a3b"
    # Untouched agent unchanged.
    assert next(a for a in agents if a["id"] == "main")["model"] == "anthropic/claude-sonnet-4-6"


def test_real_session_key_still_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-empty sessionKey is non-default, so it is still persisted."""
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir()
    (oc_dir / "openclaw.json").write_text(
        json.dumps({"agents": {"list": [{"id": "shop", "model": "m"}]}, "bindings": []})
    )
    oc = _load_acl(oc_dir, monkeypatch)
    oc.set_agent_session_key("shop", "agent:shop:proj")

    out = json.loads((oc_dir / "openclaw.json").read_text())
    agent = out["agents"]["list"][0]
    assert agent.get("metadata", {}).get("sessionKey") == "agent:shop:proj"
