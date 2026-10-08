"""The setup group: the first-run report as data, then only what is missing."""

from __future__ import annotations

import contextlib
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

import typer

import docket.config as _cfg
from docket import ui
from docket.cli import _contract
from docket.core import policy as _policy
from docket.core import secrets as _secrets

setup_app = typer.Typer(
    name="setup",
    no_args_is_help=False,
    invoke_without_command=True,
)

_PROVIDER_COMMAND = "docket setup provider add <name>"
_NOTIFY_COMMAND = "docket setup notify enable desktop"
_SANDBOX_COMMAND = "docket setup sandbox on"
_SERVICE_UNIT = Path(".config") / "systemd" / "user" / "docket-serve.service"


@dataclass(frozen=True)
class Piece:
    """One line of the first-run report: ready or not, why, and the command that fixes it."""

    name: str
    ok: bool
    reason: str
    command: str


_UNKNOWN = Piece("", True, "", "")


@dataclass(frozen=True)
class Readiness:
    """The first-run report as data; ``endpoint`` is the one required piece."""

    endpoint: Piece
    notify: Piece = _UNKNOWN
    sandbox: Piece = _UNKNOWN
    shell: Piece = _UNKNOWN
    service: Piece = _UNKNOWN

    def pieces(self) -> list[Piece]:
        return [self.endpoint, self.notify, self.sandbox, self.shell, self.service]


def _endpoint_piece() -> Piece:
    from docket.core import models_policy as _mp
    from docket.core import provider as _provider

    resolved: list[str] = []
    for role in ("lead", "implementer"):
        try:
            model = _mp.resolve_role_model(role)
            state = _provider.model_readiness(model)
        except Exception as exc:
            return Piece("model endpoint", False, f"{role}: {exc}", _PROVIDER_COMMAND)
        if not state.ready:
            reason = f"{role} -> {model}: {state.issue}"
            return Piece("model endpoint", False, reason, _PROVIDER_COMMAND)
        resolved.append(f"{role} -> {model}")
    return Piece("model endpoint", True, ", ".join(resolved), "")


def _notify_piece() -> Piece:
    from docket.core import channel as _channel

    delivering = _channel.load_catalog().delivering()
    if _channel.unreached_warning(delivering) is None:
        return Piece("notifications", True, ", ".join(delivering), "")
    return Piece("notifications", False, "console only (nobody is told)", _NOTIFY_COMMAND)


def _backend_found() -> str:
    for name in ("bwrap", "docker"):
        if shutil.which(name):
            return name
    return "none"


def _sandbox_piece() -> Piece:
    from docket.core import fleet as _fleet

    backend = _backend_found()
    if _fleet.get_isolation_enabled():
        return Piece("sandbox", True, f"on ({backend})", "")
    return Piece("sandbox", False, f"off; backend found: {backend}", _SANDBOX_COMMAND)


def _shell_name() -> str:
    name = Path(os.environ.get("SHELL", "")).name
    return name if name in ("bash", "zsh") else ""


def _shell_piece() -> Piece:
    shell = _shell_name()
    command = f"docket setup shell {shell or 'bash'}"
    rc_files = [Path.home() / ".bashrc", Path.home() / ".zshrc"]
    for rc in rc_files:
        with contextlib.suppress(OSError):
            if "docket setup shell" in rc.read_text(encoding="utf-8"):
                return Piece("shell completion", True, f"enabled in {rc.name}", "")
    return Piece("shell completion", False, "not enabled", command)


def _service_piece() -> Piece:
    if (Path.home() / _SERVICE_UNIT).is_file():
        return Piece("background service", True, "systemd user unit installed", "")
    return Piece("background service", False, "not installed", "docket start")


def readiness() -> Readiness:
    """Compute the report without printing or writing; ``init`` and ``run`` read it."""
    return Readiness(
        endpoint=_endpoint_piece(),
        notify=_notify_piece(),
        sandbox=_sandbox_piece(),
        shell=_shell_piece(),
        service=_service_piece(),
    )


def _resolve_version() -> str:
    """docket version — package metadata, falling back to the VERSION file."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("docket")
    except PackageNotFoundError:
        cand = Path(__file__).resolve().parents[3] / "VERSION"
        if cand.is_file():
            return cand.read_text(encoding="utf-8").strip()
    return "unknown"


def _version_callback(value: bool) -> None:
    if value:
        print(f"docket {_resolve_version()}")
        raise typer.Exit(0)


# -- the steps the flow runs ---------------------------------------------------------------


def step_security() -> None:
    """Tighten docket-owned config and secrets files to owner-only."""
    hardened: list[str] = []
    for path in (_cfg.FLEET_FILE, _secrets.SECRETS_FILE, _secrets.SECRETS_META_FILE):
        if not path.is_file():
            continue
        try:
            mode = os.stat(path).st_mode & 0o777
        except OSError:
            continue
        if mode & 0o077:
            with contextlib.suppress(OSError):
                os.chmod(path, 0o600)
                hardened.append(str(path))
    for path_text in hardened:
        ui.success(f"Tightened permissions to 600: {path_text}")


def step_policies() -> None:
    """Install the baseline guardrail policies; never overwrites local edits."""
    result = _policy.install_policies()
    if not result.template_dir.is_dir():
        ui.warn(f"Policy templates not found at {result.template_dir}")
        return
    count = len(result.installed)
    if count:
        ui.success(f"Installed {count} baseline {'policy' if count == 1 else 'policies'}")


# -- the report ----------------------------------------------------------------------------


def _state(piece: Piece, required: bool) -> str:
    if piece.ok:
        return "ready"
    return "missing" if required else "optional"


def _report(r: Readiness) -> None:
    ui.header("docket setup")
    rows = []
    for i, piece in enumerate(r.pieces()):
        rows.append([piece.name, _state(piece, i == 0), piece.reason, piece.command or "-"])
    ui.table(rows, ["PIECE", "STATE", "DETAIL", "COMMAND"])


def _report_json(r: Readiness) -> dict[str, object]:
    return {"ready": r.endpoint.ok, "pieces": [asdict(p) for p in r.pieces()]}


def _ask(question: str) -> bool:
    try:
        answer = input(f"{question} [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def _ran(command: str) -> None:
    ui.dim(f"ran: {command}")


def _ask_endpoint() -> int:
    from docket.cli import _setup_model
    from docket.core import provider as _prov

    catalog = _prov.load_catalog()
    names = sorted(catalog.entries)
    ui.console.print("Providers: " + ", ".join(names), markup=False)
    chosen = input("Provider [local]: ").strip() or "local"
    spec = catalog.get(chosen)
    url: str | None = None
    if spec is None:
        url = input(f"Base URL of {chosen}: ").strip()
        if not url:
            ui.error("A new provider needs its base URL")
            return 1
    needs_key = bool(spec and spec.auth.type != "none" and spec.auth.credentials)
    cred_flag = " --credential" if needs_key else ""
    _ran(f"docket setup provider add {chosen}{' ' + url if url else ''}{cred_flag}")
    return _setup_model.add_provider(chosen, url)


def _ask_telegram() -> None:
    """The wizard's Telegram step: the same one-operation connect `setup notify enable` does."""
    import getpass

    from docket.cli import _setup_notify

    chat = input("Telegram chat id: ").strip()
    if not chat:
        ui.warn("Skipped: no chat id")
        return
    token = getpass.getpass("Bot token (hidden; blank keeps the stored one): ").strip() or None
    _ran(f"docket setup notify enable telegram --chat {chat} --token")
    try:
        written = _setup_notify.enable_telegram([chat], token, test=False)
    except _setup_notify.NotifySetupError as exc:
        ui.error("Telegram not connected", str(exc))
        return
    ui.success(f"Telegram connected: chat {chat}, {len(written.bindings)} Lead binding(s)")


def _ask_optional(r: Readiness) -> None:
    from docket.cli import _setup_sandbox
    from docket.edges.adapters import system as _sys

    desktop = not r.notify.ok and _sys.desktop_notifications_available()
    if desktop and _ask("Enable desktop notifications?"):
        from docket.core import channel as _channel

        _ran(_NOTIFY_COMMAND)
        _channel.enable_channel("desktop")
        ui.success("Channel enabled: desktop")
    if not r.notify.ok and _ask("Set up Telegram?"):
        _ask_telegram()
    if not r.sandbox.ok and _backend_found() != "none" and _ask("Turn the sandbox on?"):
        _ran(_SANDBOX_COMMAND)
        _setup_sandbox.isolate("on")
    shell = _shell_name()
    if not r.shell.ok and shell and _ask(f"Enable {shell} completion?"):
        _ran(r.shell.command)
        ui.info(f'Add to your rc file: eval "$(docket setup shell {shell})"')


def run_flow(json_out: bool = False) -> int:
    """The report, then (on a TTY) only what is missing; exit 1 when the endpoint is missing."""
    r = readiness()
    if json_out:
        _contract.emit_json(_report_json(r))
        return 0 if r.endpoint.ok else 1
    _report(r)
    interactive = _contract._is_tty()
    if not r.endpoint.ok:
        if not interactive:
            ui.error("Model endpoint missing", f"Run {r.endpoint.command}")
            return 1
        if _ask_endpoint() != 0:
            return 1
        r = readiness()
        if not r.endpoint.ok:
            ui.error("Model endpoint still missing", r.endpoint.reason)
            return 1
    if interactive:
        _ask_optional(r)
    ui.success("Ready.")
    _contract.next_step("cd into a repo and run docket init")
    return 0


@setup_app.callback(invoke_without_command=True)
def setup_callback(
    ctx: typer.Context,
    json_out: bool = typer.Option(False, "--json", help="Emit the report as JSON"),
    fix: bool = typer.Option(
        False, "--fix", help="Repair permissions, ledgers and workspace files"
    ),
) -> None:
    """Set up this workstation: model endpoint, notifications, sandbox, shell.

    Bare, this is the first run: the report, then only what is missing. On a terminal it asks for what is missing, required first, and prints every
    command it runs. Off a terminal it prints the report and exits 1 when the
    model endpoint is missing. --fix repairs detected drift.

    Example: docket setup"""
    if ctx.invoked_subcommand is not None:
        return
    if fix:
        from docket.cli._setup_check import run_check

        step_security()
        step_policies()
        raise typer.Exit(run_check(json_out=json_out, do_fix=True))
    raise typer.Exit(run_flow(json_out))
