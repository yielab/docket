"""docket models provider — register a local OpenAI-compatible model endpoint.

`core/provider.py` does the pure ping → register orchestration and returns a
`ProviderRegistration`; this module renders that result and the next-steps
guidance (previously all misfiled inside core/provider.py — see ROADMAP §2,
"core has no knowledge of terminals"). Output strings are unchanged from the
pre-split flow; only the module boundary moved.
"""

from __future__ import annotations

from docket import ui
from docket.core import provider as _prov


def run_provider_add(
    name: str = _prov.DEFAULT_PROVIDER,
    base_url: str = _prov.DEFAULT_BASE_URL,
    model_id: str = _prov.DEFAULT_MODEL_ID,
    model_name: str = _prov.DEFAULT_MODEL_NAME,
    ctx: int = _prov.DEFAULT_CTX,
    max_tokens: int = _prov.DEFAULT_MAX_TOKENS,
) -> int:
    """Ping the endpoint, register the provider in openclaw.json, print next steps.

    Idempotent: re-running with the same arguments writes nothing. Returns a
    process exit code (0 on success).
    """
    ui.info(f"Checking the endpoint is alive: {base_url}/models")
    reg = _prov.register_local_provider(
        name=name,
        base_url=base_url,
        model_id=model_id,
        model_name=model_name,
        ctx=ctx,
        max_tokens=max_tokens,
    )
    _render_registration(reg)
    _print_role_split(reg.name, reg.model_id)
    return 0


def _render_registration(reg: _prov.ProviderRegistration) -> None:
    """Render the ping + register outcome in the same order as the pre-split flow."""
    if not reg.reachable:
        ui.warn(
            f"Could not reach {reg.base_url}/models — make sure your llama.cpp/LM Studio "
            "server is running first. Continuing to write config anyway."
        )

    ui.info(f"Registering provider '{reg.name}' with OpenClaw")
    if reg.changed:
        ui.success(f"Local provider wired: {reg.name}/{reg.model_id}  →  {reg.base_url}")
    else:
        ui.success(
            f"Local provider already wired: {reg.name}/{reg.model_id}  →  {reg.base_url}"
            " (no change)"
        )


def _print_role_split(name: str, model_id: str) -> None:
    """Print the role-split + smoke-test guidance."""
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
    ui.console.print(
        '  docket pod <project> delegate "Write hello.py with a pytest test, then run it"'
    )
    ui.console.print(
        "  docket pod <project> dispatch                               "
        "# lead(Claude) plan → implementer(local)"
    )
    ui.console.print(
        f"  openclaw models status --agent programmer                  "
        f"# confirm it resolves to {name}/{model_id}"
    )
