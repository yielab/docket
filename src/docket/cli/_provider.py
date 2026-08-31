"""docket models provider — register a local OpenAI-compatible model endpoint.

`core/provider.py` does the pure ping → register orchestration and returns a
`ProviderRegistration`; this module renders that result and the next-steps
guidance, keeping presentation-layer output out of `core` ("core has no
knowledge of terminals").
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
    """Ping the endpoint, register the provider in docket's fleet registry, print next steps.

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
    if not reg.reachable:
        ui.error(
            f"Could not reach {reg.base_url}/models. Provider was not registered; "
            "start the OpenAI-compatible server and retry the same command."
        )
        return 1
    _render_registration(reg)
    _print_local_selection(reg.name, reg.model_id)
    return 0


def _render_registration(reg: _prov.ProviderRegistration) -> None:
    """Render the ping + register outcome in the same order as the pre-split flow."""
    ui.info(f"Registering provider '{reg.name}'")
    if reg.changed:
        ui.success(f"Local provider wired: {reg.name}/{reg.model_id}  →  {reg.base_url}")
    else:
        ui.success(
            f"Local provider already wired: {reg.name}/{reg.model_id}  →  {reg.base_url}"
            " (no change)"
        )


def _print_local_selection(name: str, model_id: str) -> None:
    """Print a keyless all-local selection path without implying a vendor subscription."""
    ui.console.print()
    ui.console.print("Next — select the reachable local provider:")
    ui.console.print()
    if name == "local":
        ui.console.print("  docket models preset local")
        ui.console.print(f"    # selects the registered model: {name}/{model_id}")
    else:
        for role in (
            "manager",
            "programmer",
            "reviewer",
            "tester",
            "knowledge",
            "security",
            "repo",
        ):
            ui.console.print(f"  docket models set {role:<10} {name}/{model_id}")
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
        "# all roles use the selected local endpoint"
    )
    ui.console.print(
        "  docket profile programmer                                   "
        f"# confirm it resolves to {name}/{model_id}"
    )
