"""Local provider registration — port of scripts/wire-local-provider.sh.

Registers a local OpenAI-compatible model endpoint (llama.cpp / LM Studio /
vLLM) with the OpenClaw daemon so docket can route agent roles to it, e.g.
`docket models set programmer local/qwen3-30b-a3b`.

Run once, after the local inference server is up and answering on its /v1
endpoint. Idempotent — safe to re-run to update the model / context.

All openclaw.json knowledge lives in the ACL (edges/adapters/openclaw.py); this
module only orchestrates the ping → register → print-next-steps flow.
"""

from __future__ import annotations

import urllib.error
import urllib.request

from docket import ui
from docket.edges.adapters import openclaw as _oc

# Defaults match the Qwen3-30B-A3B llama.cpp setup (server on :8080, -c 16384),
# mirroring the script's top-of-file defaults.
DEFAULT_PROVIDER = "local"
DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_MODEL_ID = "qwen3-30b-a3b"
DEFAULT_MODEL_NAME = "Qwen3 30B-A3B (local)"
DEFAULT_CTX = 16384
DEFAULT_MAX_TOKENS = 8192


def ping_endpoint(base_url: str, timeout: float = 5.0) -> bool:
    """Return True if GET <base_url>/models responds (any 2xx/whatever, no error).

    Mirrors `curl -fsS --max-time 5 "$BASE_URL/models"` in the script. Kept as a
    standalone function so tests can monkeypatch it (no real network in tests).
    """
    url = f"{base_url}/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def register_local_provider(
    name: str = DEFAULT_PROVIDER,
    base_url: str = DEFAULT_BASE_URL,
    model_id: str = DEFAULT_MODEL_ID,
    model_name: str = DEFAULT_MODEL_NAME,
    ctx: int = DEFAULT_CTX,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> int:
    """Ping the endpoint, register the provider in openclaw.json, print next steps.

    Idempotent: re-running with the same arguments writes nothing. Returns a
    process exit code (0 on success).
    """
    # 1. Liveness probe (non-fatal — the script writes config anyway).
    ui.info(f"Checking the endpoint is alive: {base_url}/models")
    if not ping_endpoint(base_url):
        ui.warn(
            f"Could not reach {base_url}/models — make sure your llama.cpp/LM Studio "
            "server is running first. Continuing to write config anyway."
        )

    # 2. Register (idempotent via the ACL).
    ui.info(f"Registering provider '{name}' with OpenClaw")
    changed = _oc.add_local_provider(name, base_url, model_id, model_name, ctx, max_tokens)
    if changed:
        ui.success(f"Local provider wired: {name}/{model_id}  →  {base_url}")
    else:
        ui.success(f"Local provider already wired: {name}/{model_id}  →  {base_url} (no change)")

    # 3. Print the smart-planner / local-executor role-split commands.
    _print_role_split(name, model_id)
    return 0


def _print_role_split(name: str, model_id: str) -> None:
    """Print the role-split + smoke-test guidance (mirrors the script's heredoc)."""
    ui.console.print()
    ui.console.print("Next — apply the smart-planner / local-executor role split:")
    ui.console.print()
    ui.console.print(
        "  docket models set manager    anthropic/claude-sonnet-4-6"
        "   # architecture & delegation (smart)"
    )
    ui.console.print(
        "  docket models set reviewer   anthropic/claude-sonnet-4-6"
        "   # catches local mistakes (recommended)"
    )
    ui.console.print(
        f"  docket models set programmer {name}/{model_id}"
        "            # implementation (local, free)"
    )
    ui.console.print(f"  docket models set tester     {name}/{model_id}")
    ui.console.print(f"  docket models set knowledge  {name}/{model_id}")
    ui.console.print(
        f"  docket models set repo       {name}/{model_id}"
        "            # project agents execute locally"
    )
    ui.console.print(f"  docket models set task       {name}/{model_id}")
    ui.console.print(
        "  docket models                                               "
        "# confirm the role→model table"
    )
    ui.console.print()
    ui.console.print("Then smoke-test the split:")
    ui.console.print()
    ui.console.print("  docket team status")
    ui.console.print('  docket team delegate "Write hello.py with a pytest test, then run it"')
    ui.console.print(
        "  docket team queue                                           "
        "# manager(Claude) plan → programmer(local)"
    )
    ui.console.print(
        f"  openclaw models status --agent programmer                  "
        f"# confirm it resolves to {name}/{model_id}"
    )
