"""Bind the real tool gate, git, process and jail adapters of the private implementation.

``docket.bootstrap`` does this for the CLI and the server; the runtime ships a closure that
excludes it, so this module is the runtime's entry point for the ports its closure uses. Importing
``docket_runtime`` imports it first.
"""

from __future__ import annotations

from docket_runtime._internal.docket.agent.ports import bind_tool_gate
from docket_runtime._internal.docket.governance import gate as _gate
from docket_runtime._internal.docket.governance import secrets as _secrets
from docket_runtime._internal.docket.governance import security as _security
from docket_runtime._internal.docket.kernel.ports import bind_git, bind_jail, bind_process
from docket_runtime._internal.docket.models import catalog as _catalog
from docket_runtime._internal.docket.platform import git as _git
from docket_runtime._internal.docket.platform import process as _process
from docket_runtime._internal.docket.sandbox.launch import Launcher
from docket_runtime._internal.docket.teams import fleet as _fleet


def _credential_sources() -> set[str]:
    names = set(_secrets.secrets_keys())
    for spec in _catalog.load_catalog().entries.values():
        names.update(spec.auth.credentials)
    return names


def bind_adapters() -> None:
    bind_tool_gate(_gate)
    bind_git(_git)
    bind_process(_process)
    bind_jail(
        Launcher(
            recorded_backend=_fleet.get_sandbox_backend,
            credential_source=_credential_sources,
            high_risk=_security.match_high_risk,
        )
    )


bind_adapters()
