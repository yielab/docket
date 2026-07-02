"""Local provider registration.

Registers a local OpenAI-compatible model endpoint (llama.cpp / LM Studio /
vLLM) with the OpenClaw daemon so docket can route agent roles to it, e.g.
`docket models set programmer local/qwen3-30b-a3b`.

Run once, after the local inference server is up and answering on its /v1
endpoint. Idempotent — safe to re-run to update the model / context.

All openclaw.json knowledge lives in the ACL (edges/adapters/openclaw.py); this
module only orchestrates the ping → register step. It has no knowledge of
terminals (ROADMAP §2) — it returns a typed result; `cli/_provider.py` renders
it and prints the next-steps guidance.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass

from docket.edges.adapters import openclaw as _oc

# Defaults match the Qwen3-30B-A3B llama.cpp setup (server on :8080, -c 16384).
DEFAULT_PROVIDER = "local"
DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_MODEL_ID = "qwen3-30b-a3b"
DEFAULT_MODEL_NAME = "Qwen3 30B-A3B (local)"
DEFAULT_CTX = 16384
DEFAULT_MAX_TOKENS = 8192


def ping_endpoint(base_url: str, timeout: float = 5.0) -> bool:
    """Return True if GET <base_url>/models responds (any 2xx/whatever, no error).

    Kept as a standalone function so tests can monkeypatch it (no real network in tests).
    """
    url = f"{base_url}/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


@dataclass(frozen=True)
class ProviderRegistration:
    """Outcome of register_local_provider(). Rendered by cli/_provider.py."""

    name: str
    base_url: str
    model_id: str
    model_name: str
    ctx: int
    max_tokens: int
    reachable: bool
    changed: bool


def register_local_provider(
    name: str = DEFAULT_PROVIDER,
    base_url: str = DEFAULT_BASE_URL,
    model_id: str = DEFAULT_MODEL_ID,
    model_name: str = DEFAULT_MODEL_NAME,
    ctx: int = DEFAULT_CTX,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> ProviderRegistration:
    """Ping the endpoint and register the provider in openclaw.json.

    Pure orchestration — no output. Idempotent: re-running with the same
    arguments writes nothing (``changed`` comes back False).
    """
    reachable = ping_endpoint(base_url)
    changed = _oc.add_local_provider(name, base_url, model_id, model_name, ctx, max_tokens)
    return ProviderRegistration(
        name=name,
        base_url=base_url,
        model_id=model_id,
        model_name=model_name,
        ctx=ctx,
        max_tokens=max_tokens,
        reachable=reachable,
        changed=changed,
    )
