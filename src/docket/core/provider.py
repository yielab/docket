"""Local provider registration.

Registers a local OpenAI-compatible model endpoint (llama.cpp / LM Studio /
vLLM) with docket's own fleet registry so docket can route agent roles to it,
e.g. `docket models set programmer local/qwen3-30b-a3b`.

Run once, after the local inference server is up and answering on its /v1
endpoint. Idempotent — safe to re-run to update the model / context.

The provider definition lives in fleet.json (`core/fleet.py`'s
`add_local_provider`/`get_local_provider`), which is what
`edges/adapters/llm.py`'s `resolve_endpoint` reads to build a chat client for
docket's own turn loop. This module still has no knowledge of terminals — it
returns a typed result; `cli/_provider.py` renders it and prints the
next-steps guidance.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from docket.core import fleet as _fleet

# Defaults match the Qwen3-30B-A3B llama.cpp setup (server on :8080, -c 16384).
DEFAULT_PROVIDER = "local"
DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_MODEL_ID = "qwen3-30b-a3b"
DEFAULT_MODEL_NAME = "Qwen3 30B-A3B (local)"
DEFAULT_CTX = 16384
DEFAULT_MAX_TOKENS = 8192

_PROVIDER_CREDENTIALS: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "google": ("GOOGLE_AI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "ai-gateway": ("AI_GATEWAY_API_KEY", "VERCEL_OIDC_TOKEN"),
}


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


def local_provider_config(
    base_url: str,
    model_id: str,
    model_name: str,
    ctx: int,
    max_tokens: int,
) -> dict[str, object]:
    """Build the provider definition for a local OpenAI-compatible endpoint.

    apiKey is a literal dummy ("local") — llama.cpp ignores it, but the shape
    mirrors what a provider block has always looked like so
    ``edges/adapters/llm.py``'s ``resolve_endpoint`` needs no special-casing.
    Cost is zero (local inference).
    """
    return {
        "baseUrl": base_url,
        "apiKey": "local",
        "api": "openai-completions",
        "models": [
            {
                "id": model_id,
                "name": model_name,
                "reasoning": False,
                "input": ["text"],
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                "contextWindow": int(ctx),
                "maxTokens": int(max_tokens),
            }
        ],
    }


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


@dataclass(frozen=True)
class ModelReadiness:
    """Structural readiness of one selected runtime model, with no secret values."""

    model: str
    provider: str
    base_url: str
    ready: bool
    credential_name: str
    credential_present: bool
    context_window: int | None
    max_output: int | None
    issue: str


def model_readiness(model: str) -> ModelReadiness:
    """Resolve the selected model and require credentials only for known hosted routes.

    This is deliberately structural: it does not spend a remote model request. Local provider
    reachability is established at registration time; the deterministic driver test owns actual
    Chat Completions/tool-wire capability.
    """
    from docket.core import secrets as _secrets
    from docket.edges.adapters import llm as _llm

    provider, _, _model_id = model.partition("/")
    credential_names = _PROVIDER_CREDENTIALS.get(provider, ())
    credential_name = credential_names[0] if credential_names else ""
    credential_present = any(
        bool(os.environ.get(name, "").strip()) or bool(_secrets.secret_value(name))
        for name in credential_names
    )
    endpoint = _llm.resolve_endpoint(model)
    if endpoint is None:
        detail = (
            f"{credential_name} is present but is not an endpoint" if credential_present else ""
        )
        issue = detail or "no callable OpenAI-compatible endpoint is configured"
        return ModelReadiness(
            model=model,
            provider=provider,
            base_url="",
            ready=False,
            credential_name=credential_name,
            credential_present=credential_present,
            context_window=None,
            max_output=None,
            issue=issue,
        )

    if credential_names and not endpoint.api_key:
        return ModelReadiness(
            model=model,
            provider=provider,
            base_url=endpoint.base_url,
            ready=False,
            credential_name=credential_name,
            credential_present=False,
            context_window=endpoint.context_window_tokens,
            max_output=endpoint.max_output_tokens,
            issue=f"{credential_name} is required for the resolved endpoint",
        )

    return ModelReadiness(
        model=model,
        provider=provider,
        base_url=endpoint.base_url,
        ready=True,
        credential_name=credential_name,
        credential_present=bool(endpoint.api_key),
        context_window=endpoint.context_window_tokens,
        max_output=endpoint.max_output_tokens,
        issue="",
    )


def register_local_provider(
    name: str = DEFAULT_PROVIDER,
    base_url: str = DEFAULT_BASE_URL,
    model_id: str = DEFAULT_MODEL_ID,
    model_name: str = DEFAULT_MODEL_NAME,
    ctx: int = DEFAULT_CTX,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> ProviderRegistration:
    """Ping the endpoint and register the provider in docket's fleet registry.

    Pure orchestration — no output. Idempotent: re-running with the same
    arguments writes nothing (``changed`` comes back False).
    """
    reachable = ping_endpoint(base_url)
    changed = (
        _fleet.add_local_provider(name, base_url, model_id, model_name, ctx, max_tokens)
        if reachable
        else False
    )
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
