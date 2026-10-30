from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from docket.interfaces.cli.render import ui
from docket.kernel.home import current_home
from docket.kernel.ports import jail as _jail
from docket.observability import exporter as _exporter
from docket.operator import load_catalog, unreached_warning
from docket.teams import fleet as _fleet
from docket.teams import network_posture as _np
from docket.teams import pod_settings as _pod_settings

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _exporter_report() -> list[dict[str, Any]]:
    """One row per enabled exporter: name, failed exports since last success, privacy label and
    the non-loopback host receiving content (else None)."""
    catalog = _exporter.load_catalog()
    health = _exporter.read_health()
    rows: list[dict[str, Any]] = []
    for name in sorted(n for n, spec in catalog.entries.items() if spec.enabled):
        spec = catalog.entries[name]
        host: str | None = None
        if spec.privacy_label in ("conversation", "full"):
            h = urlsplit(spec.endpoint).hostname or spec.endpoint
            host = h if h not in _LOOPBACK_HOSTS else None
        rows.append(
            {
                "name": name,
                "failed": int(health.get(name, {}).get("failed") or 0),
                "privacy": spec.privacy_label,
                "host": host,
            }
        )
    return rows


def check_exporters() -> int:
    """Warn for every enabled exporter whose health shows a failure since its last success,
    plus informational lines (not counted as issues) for a `conversation`/`full` exporter
    reaching a non-loopback host."""
    ui.section("Exporters:")
    rows = _exporter_report()
    issues = 0
    if not rows:
        ui.dim("  No exporters enabled")
    for row in rows:
        name = row["name"]
        if row["failed"] > 0:
            ui.warn(f"  {name}: {row['failed']} failed export(s) — docket setup export test {name}")
            issues += 1
        else:
            ui.success(f"  {name}: healthy")
        if row["host"]:
            ui.info(f"  {name}: privacy '{row['privacy']}' shares content with {row['host']}")
    return issues


def _check_notifications(ids: list[str]) -> int:
    """Warn when no enabled channel delivers beyond the console -- a parked task would wait
    unseen. Counted as an issue only once a project agent exists to park anything."""
    ui.section("Notifications:")
    delivering = load_catalog().delivering()
    text = unreached_warning(delivering)
    if text is None:
        ui.success(f"  Delivering: {', '.join(delivering)}")
        return 0
    if ids:
        ui.console.print(f"[red]✗[/red]   {text}")
        return 1
    ui.dim(f"  {text}")
    return 0


def _docker_image_has_git() -> bool | None:
    """The jail image's git probe, only when docker is the backend in use and isolation is not off;
    None when it does not apply."""
    if not _fleet.get_isolation_enabled():
        return None
    if _jail.sandbox_availability().backend != "docker":
        return None
    return _jail.docker_image_has_git()


def _check_security_gates(ids: list[str] | None = None) -> int:
    """Isolation posture + the always-on tool-call gate.

    The gate itself is unconditionally active on every tool call docket dispatches (see
    specs/functional/security-gates.spec.md) — there is no "is it enabled" question left to ask,
    only whether execution is sandboxed."""
    ui.section("Security gates:")

    ui.success("  Tool-call gate: always active (policy engine + high-risk command classifier)")

    state = _fleet.get_isolation_state()
    enabled = _fleet.get_isolation_enabled()
    if not enabled:
        ui.dim(
            f"  Workspace isolation: {'off (explicit)' if state == 'off' else state} -- "
            "docket setup sandbox on (needs landlock on Linux 5.13+, seatbelt on macOS, or a chosen docker)"
        )
    else:
        backend = _jail.sandbox_availability().backend
        if backend == "none":
            ui.warn(
                f"  Workspace isolation: {state}, but no backend is usable -- turns will be "
                "refused. Use Linux 5.13+ or macOS, choose docker (docket setup sandbox backend docker), or docket setup sandbox off"
            )
        else:
            ui.success(f"  Workspace isolation: {state}, backend {backend}")
            if _docker_image_has_git() is False:
                ui.warn(
                    f"  Docker jail image {current_home().sandbox_docker_image} has no git -- a jailed "
                    "commit will fail. Set DOCKET_SANDBOX_IMAGE=<an image with git>"
                )

    issues = 0
    if ids and _jail.sandbox_availability().backend == "none":
        ui.console.print(
            "✗   Sandbox: no usable sandbox backend on this machine -- "
            "docket setup sandbox shows what is missing",
            markup=False,
        )
        issues = 1

    posture = _np.global_posture()
    if posture.enforced:
        ui.success(f"  Network: {posture.line}")
    elif posture.mode == "open":
        ui.dim(
            "  Network: open (granted) -- docket setup sandbox network none to cut the sandbox's network"
        )
    elif posture.scope == "default":
        ui.dim(f"  Network: {posture.line}; docket setup sandbox network open to grant it")
    else:
        ui.warn(
            f"  Network: {posture.line} -- turns will be refused. "
            "docket setup sandbox on, or docket setup sandbox network open"
        )

    granted = _pod_settings.network_grant_pods(ids or [])
    if granted:
        ui.warn(
            f"  Pod network grant: {', '.join(granted)} -- {_pod_settings.NETWORK_GRANT_REACH}; "
            "docket pod set network none --pod <name> withdraws it"
        )

    return issues
