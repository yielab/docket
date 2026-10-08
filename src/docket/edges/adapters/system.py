"""System adapter: typed wrappers over docker, bwrap, and git.

Every shell-out to a container runtime, sandbox tool, or git lives here. Every subprocess call
catches FileNotFoundError / TimeoutExpired / OSError and degrades gracefully so a missing binary
never crashes a command. Functions are module-level and typed so callers can monkeypatch them.
Imports ``docket.core.security`` for ``match_high_risk``. ``run_verify_cmd`` is the only function
here that runs a free-form command through a real shell (``shell=True``); every other function
builds a fixed argv itself -- see ``specs/functional/security-gates.spec.md`` for the scoping
rationale, which also covers the exec-sandbox section below (mechanism only; the decision to use
one belongs to ``core/tools.py``'s ``ToolContext.sandbox``).
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import docket.config as _cfg
from docket.core import security as _sec

# Kept short so a hung subprocess never blocks a CLI command.
_QUERY_TIMEOUT = 5


def _which(binary: str) -> bool:
    """Return True if `binary` resolves on PATH (degrades to False on error)."""
    try:
        result = subprocess.run(
            ["command", "-v", binary],
            capture_output=True,
            timeout=_QUERY_TIMEOUT,
        )
        if result.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    # `command` is a shell builtin and may not exist as an executable; fall back
    # to a PATH scan so detection works regardless of how we are invoked.
    path = os.environ.get("PATH", "")
    for directory in path.split(os.pathsep):
        if directory and os.access(os.path.join(directory, binary), os.X_OK):
            return True
    return False


def secret_tool_available() -> bool:
    """Return True if the `secret-tool` (libsecret) binary is on PATH."""
    return _which("secret-tool")


def desktop_notifications_available() -> bool:
    """True when the `desktop` channel dialect could deliver here: `osascript` on macOS, or a
    graphical session (`DISPLAY`/`WAYLAND_DISPLAY`) plus `notify-send` elsewhere."""
    if sys.platform == "darwin":
        return _which("osascript")
    has_session = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return has_session and _which("notify-send")


def secret_tool_lookup(service: str, key: str) -> str | None:
    """Look up one secret's value via `secret-tool lookup`; returns ``None``
    on any failure (missing binary, timeout, no match) -- treated as "no
    value", never an error, by `core/secrets.py`'s backend."""
    try:
        result = subprocess.run(
            ["secret-tool", "lookup", "service", service, "key", key],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return result.stdout or None


def secret_tool_store(service: str, key: str, value: str) -> bool:
    """Store one secret via `secret-tool store` (value piped over stdin, never argv). Returns
    ``False`` on any failure -- unlike `secret_tool_lookup`, the caller treats that as an
    error, since a silent fallback to plaintext storage would defeat the keyring backend."""
    try:
        result = subprocess.run(
            ["secret-tool", "store", "--label", f"docket: {key}", "service", service, "key", key],
            input=value,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def secret_tool_clear(service: str, key: str) -> bool:
    """Remove one secret via `secret-tool clear`; best-effort like `secret_tool_lookup` --
    returns ``False`` on any failure, but the caller does not fail the surrounding command
    on that (the secrets.json index entry is removed either way)."""
    try:
        result = subprocess.run(
            ["secret-tool", "clear", "service", service, "key", key],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def docker_available() -> bool:
    """Return True if a docker binary is on PATH (does not verify daemon reachability)."""
    return _which("docker")


# ── exec sandbox ─────────────────────────────────────────────────────────────
#
# `edges/adapters/toolbox.py`'s `run_bash` has no jail of its own -- the
# gate decides whether a command may run at all, not what it can reach once
# it does. These functions are the mechanism half of that: detecting which
# jail backend is actually usable on this host (not just installed) and
# building the argv that applies it. The *decision* to ask for one lives on
# `ToolContext.sandbox` (`core/tools.py`, opt-in, default "off") -- this
# module never decides, only detects and constructs, matching the existing
# split with `core.security`'s classifier.

SandboxBackend = Literal["docker", "bwrap", "none"]

# Detection probes must be fast (they run on every "auto" call) and must
# never hang a tool call over a jail that turns out to be unusable.
_SANDBOX_PROBE_TIMEOUT = 5


def docker_daemon_reachable() -> bool:
    """True if docker is on PATH AND its daemon answers, unlike `docker_available()` (binary only). A
    daemon absent or unreachable (rootless setups, a service never started) is common enough that
    treating "present" as "usable" would be a silent, incorrect degrade."""
    if not docker_available():
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=_SANDBOX_PROBE_TIMEOUT,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def bwrap_available() -> bool:
    """True if bwrap is on PATH AND can actually build a sandbox right now. The binary alone is not
    enough: disabled unprivileged user namespaces (hardened hosts, some containerized CI) make bwrap
    fail at its first real invocation despite being installed -- this runs a real smoke test, not `which`."""
    if not _which("bwrap"):
        return False
    try:
        result = subprocess.run(
            [
                "bwrap",
                "--unshare-all",
                "--die-with-parent",
                "--ro-bind",
                "/",
                "/",
                "--",
                "/bin/true",
            ],
            capture_output=True,
            timeout=_SANDBOX_PROBE_TIMEOUT,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


@dataclass(frozen=True)
class SandboxAvailability:
    """One probe of both backends: the strongest usable one, plus the raw per-backend result
    explaining why not. Answers "is a jail available", never "did this command run in one" -- see
    ``specs/functional/security-gates.spec.md``'s capability-reporting rule."""

    backend: SandboxBackend
    docker: bool
    bwrap: bool


def sandbox_availability() -> SandboxAvailability:
    """Probe both backends once; report the first usable one: bwrap (smoke test passes)
    beats docker (daemon reachable) beats none.
    `DOCKET_SANDBOX_BACKEND` overrides this for tests or an operator."""
    docker_ok = docker_daemon_reachable()
    bwrap_ok = bwrap_available()
    override = os.environ.get("DOCKET_SANDBOX_BACKEND")
    backend: SandboxBackend
    if override in ("docker", "bwrap", "none"):
        backend = override  # type: ignore[assignment]
    elif bwrap_ok:
        backend = "bwrap"
    elif docker_ok:
        backend = "docker"
    else:
        backend = "none"
    return SandboxAvailability(backend=backend, docker=docker_ok, bwrap=bwrap_ok)


def git_dirs(root: Path) -> list[Path]:
    """The repository dirs of *root* when it is inside a repo or linked worktree, else [].
    A commit writes both the per-worktree dir (index) and the common dir (objects, refs), so a
    jail that can commit must mount them read-write."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--absolute-git-dir", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=_SANDBOX_PROBE_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    out: list[Path] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        path = Path(line)
        if not path.is_absolute():
            path = Path(root) / path
        path = path.resolve()
        if path not in out:
            out.append(path)
    return out


_SUBMODULE_DEPTH = 8


def _submodule_git_dirs(base: Path) -> list[Path]:
    """Git dirs of submodules under ``base/modules`` (any depth): a directory holding ``HEAD``.
    Walks the filesystem only -- never runs git in a submodule -- and never follows symlinks."""
    found: list[Path] = []

    def walk(directory: Path, depth: int) -> None:
        if depth > _SUBMODULE_DEPTH:
            return
        try:
            children = sorted(c for c in directory.iterdir() if c.is_dir() and not c.is_symlink())
        except OSError:
            return
        for child in children:
            if (child / "HEAD").is_file():
                found.append(child)
                walk(child / "modules", depth + 1)
            else:
                walk(child, depth + 1)

    walk(base / "modules", 0)
    return found


def _submodule_worktree_git_file(subgit: Path) -> Path | None:
    """The ``.git`` file of a submodule's checkout, located through the ``worktree =`` line of its
    git dir's config (read as text); None when absent or not a file."""
    try:
        text = (subgit / "config").read_text(errors="replace")
    except OSError:
        return None
    match = re.search(r"^\s*worktree\s*=\s*(.+?)\s*$", text, re.MULTILINE)
    if not match:
        return None
    checkout = Path(match.group(1))
    if not checkout.is_absolute():
        checkout = subgit / checkout
    dotgit = Path(os.path.normpath(checkout)) / ".git"
    return dotgit if dotgit.is_file() else None


def _guarded_paths(root: Path, dirs: list[Path]) -> list[Path]:
    """Every path under the git dirs (and root's ``.git`` file) that the operator's next host-side
    git command would execute or trust, so the jail must not be able to write it."""
    gitdir, common = dirs[0], dirs[-1]
    guarded = [
        common / "hooks",
        common / "config",
        gitdir / "config.worktree",
        common / "info" / "attributes",
    ]
    if (root / ".git").is_file():
        guarded.append(root / ".git")
    if gitdir != common:
        guarded += [gitdir / "gitdir", gitdir / "commondir"]
    for base in dict.fromkeys(dirs):
        for sub in _submodule_git_dirs(base):
            guarded += [sub / "hooks", sub / "config", sub / "config.worktree"]
            guarded += [sub / "info" / "attributes"]
            checkout_git = _submodule_worktree_git_file(sub)
            if checkout_git is not None:
                guarded.append(checkout_git)
    for g in guarded:
        _materialize_guard(g)
    return [g for g in guarded if g.is_dir() or g.is_file()]


def _materialize_guard(path: Path) -> None:
    """Create an absent ``hooks`` dir or ``info/attributes`` file, empty, so it can be bound
    read-only: a path missing at jail start would otherwise be creatable from inside it."""
    if path.exists():
        return
    with contextlib.suppress(OSError):
        if path.name == "hooks" and path.parent.is_dir():
            path.mkdir()
        elif path.name == "attributes" and path.parent.parent.is_dir():
            path.parent.mkdir(exist_ok=True)
            path.touch()


def _mount_dirs(roots: tuple[Path, ...]) -> tuple[list[str], list[str]]:
    """Read-write mounts (roots plus their repository dirs) and the read-only overlays on top.
    Hooks, config, attributes, submodule equivalents and ``.git`` pointer files stay read-only: a
    writable one lets the jail plant code the operator's next host git command runs. Bind them last."""
    rw: list[str] = []
    ro: list[str] = []
    for root in roots:
        dirs = git_dirs(root)
        resolved_root = root.resolve()
        for path in [resolved_root, *dirs]:
            if str(path) not in rw:
                rw.append(str(path))
        if dirs:
            for guarded in _guarded_paths(resolved_root, dirs):
                if str(guarded) not in ro:
                    ro.append(str(guarded))
    return rw, ro


def bwrap_argv(roots: tuple[Path, ...], command: str, network: bool = True) -> list[str]:
    """Build the bwrap argv that jails *command* to *roots*: host filesystem
    read-only except *roots* (read-write on top), the same "contain to known
    roots" shape `toolbox.resolve_within` uses for file tools. `--unshare-all`
    isolates pid/ipc/uts/mount, so killing this call's process group cannot
    leave a namespace orphan (Linux tears the pid namespace down with it).
    Network stays shared unless *network* is False, which leaves the fresh network namespace
    ``--unshare-all`` made empty -- see ``specs/functional/security-gates.spec.md``."""
    return [*_bwrap_prefix(roots, network), "/bin/sh", "-c", command]


def bwrap_command_argv(roots: tuple[Path, ...], argv: list[str], network: bool = True) -> list[str]:
    """The same jail as :func:`bwrap_argv`, running *argv* directly (no shell), stdio passed through."""
    return [*_bwrap_prefix(roots, network), *argv]


_GIT_IDENTITY_VARS = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
)


def git_identity_env(root: Path) -> dict[str, str]:
    """The operator's git identity for a jailed command in *root*: the four ``GIT_AUTHOR_*``/
    ``GIT_COMMITTER_*`` variables when set, else ``user.name``/``user.email`` as git resolves
    them on the host there. Identity only, never a credential; empty when git knows none."""
    found = {k: os.environ[k] for k in _GIT_IDENTITY_VARS if os.environ.get(k)}
    if len(found) == len(_GIT_IDENTITY_VARS) or not git_available():
        return found
    resolved: dict[str, str] = {}
    for key in ("name", "email"):
        try:
            out = subprocess.run(
                ["git", "-C", str(root), "config", "--get", f"user.{key}"],
                capture_output=True,
                text=True,
                timeout=_QUERY_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out.returncode == 0 and out.stdout.strip():
            resolved[key] = out.stdout.strip()
    for var in _GIT_IDENTITY_VARS:
        value = resolved.get(var.rsplit("_", 1)[1].lower())
        if var not in found and value:
            found[var] = value
    return found


def _bwrap_prefix(roots: tuple[Path, ...], network: bool) -> list[str]:
    argv = [
        "bwrap",
        "--unshare-all",
        *(["--share-net"] if network else []),
        "--die-with-parent",
        "--ro-bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
    ]
    rw, ro = _mount_dirs(roots)
    for resolved in rw:
        argv += ["--bind", resolved, resolved]
    for guarded in ro:
        argv += ["--ro-bind", guarded, guarded]
    argv.append("--")
    return argv


def docker_run_argv(
    container_name: str,
    roots: tuple[Path, ...],
    command: str,
    env: dict[str, str] | None,
    network: bool = True,
) -> list[str]:
    """Build the ``docker run`` argv that jails *command* to *roots*: each root bind-mounted read-write,
    nothing else of the host visible. Runs as the caller's uid/gid so mounted files are not left root-owned.
    *env* injects only `ToolContext.env` (e.g. `DOCKET_SCRATCH_DIR`), never the full host environment --
    see ``specs/functional/security-gates.spec.md`` for why (env minimization) and the network-bridge rationale."""
    return [*_docker_prefix(container_name, roots, env, network), "sh", "-c", command]


def docker_command_argv(
    container_name: str,
    roots: tuple[Path, ...],
    argv: list[str],
    env: dict[str, str] | None,
    network: bool = True,
) -> list[str]:
    """The same jail as :func:`docker_run_argv`, running *argv* directly with stdin kept open (``-i``)."""
    return [*_docker_prefix(container_name, roots, env, network, interactive=True), *argv]


def _docker_prefix(
    container_name: str,
    roots: tuple[Path, ...],
    env: dict[str, str] | None,
    network: bool,
    interactive: bool = False,
) -> list[str]:
    argv = [
        "docker",
        "run",
        "--rm",
        *(["-i"] if interactive else []),
        "--name",
        container_name,
        "--user",
        f"{os.getuid()}:{os.getgid()}",
    ]
    if not network:
        argv += ["--network", "none"]
    rw, ro = _mount_dirs(roots)
    for resolved in rw:
        argv += ["-v", f"{resolved}:{resolved}"]
    for guarded in ro:
        argv += ["-v", f"{guarded}:{guarded}:ro"]
    argv += ["-w", str(roots[0].resolve())]
    for key, value in (env or {}).items():
        argv += ["-e", f"{key}={value}"]
    argv.append(_cfg.SANDBOX_DOCKER_IMAGE)
    return argv


def docker_image_has_git(image: str | None = None) -> bool | None:
    """True when *image* (default the configured jail image) has ``git`` on its PATH, False when it
    does not or is not present locally, None when the probe itself could not run or timed out."""
    try:
        result = subprocess.run(
            [
                *["docker", "run", "--rm", "--pull", "never"],
                image or _cfg.SANDBOX_DOCKER_IMAGE,
                *["sh", "-c", "command -v git"],
            ],
            capture_output=True,
            timeout=_IMAGE_PROBE_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return result.returncode == 0


def docker_kill(container_name: str) -> None:
    """Force-stop (and, via the original run's ``--rm``, remove) a docker-jailed
    run by name. Needed because ``docker run``'s own CLI process group does
    NOT reach the container the daemon actually runs -- killing only the CLI
    leaves it running (see ``specs/functional/security-gates.spec.md``).
    Swallows every failure: runs from a timeout handler, where a hung kill
    must not become a second hang."""
    import contextlib

    with contextlib.suppress(subprocess.TimeoutExpired, OSError):
        subprocess.run(["docker", "kill", container_name], capture_output=True, timeout=10)


_IMAGE_PROBE_TIMEOUT = 30
_VERIFY_MAX_OUTPUT = 4096  # cap trace payload so one bad run doesn't bloat traces


def credential_names() -> set[str]:
    """Every environment name docket treats as a credential: ``DOCKET_LLM_API_KEY``,
    ``TELEGRAM_BOT_TOKEN``, each name the provider catalog declares and each in the secret store.
    Reads files only; never creates the home."""
    from docket.core import provider as _provider
    from docket.core import secrets as _secrets

    names = {"DOCKET_LLM_API_KEY", "TELEGRAM_BOT_TOKEN"}
    names.update(_secrets.secrets_keys())
    for spec in _provider.load_catalog().entries.values():
        names.update(spec.auth.credentials)
    return names


def task_environment(overlay: dict[str, str] | None = None) -> dict[str, str]:
    """The host environment minus docket's credentials (``credential_names``), with *overlay*
    applied last."""
    names = credential_names()
    merged = {k: v for k, v in os.environ.items() if k not in names}
    if overlay:
        merged.update(overlay)
    return merged


def run_verify_cmd(
    cmd: str, cwd: str, timeout: int = 120, env: dict[str, str] | None = None
) -> tuple[bool, str]:
    """Run a user-supplied verification command in *cwd*. Returns
    ``(passed, combined_output)`` capped at _VERIFY_MAX_OUTPUT; the caller
    must redact secrets before tracing it. Never raises: non-zero exit,
    timeout, missing binary, or OS error all return ``False`` with a short
    error string instead.

    *cmd* is classified against ``core.security``'s high-risk classes and
    fails closed -- refused outright, never run -- before the subprocess
    starts. That is the only honest posture here: this call is synchronous
    inside a dispatch hop, with no interactive approver reachable (see
    ``specs/functional/security-gates.spec.md``). ``cwd``/``timeout`` are
    never classified: they are plumbing, not operator-composed shell text. *env*, when
    given, is merged over the inherited environment minus docket's credentials.

    Runs in its own session (``start_new_session=True``) so a timeout can kill the
    command's whole process group, not just the immediate ``sh`` child -- otherwise a
    command that backgrounds work (``build & wait``, a test runner spawning workers)
    leaves orphans behind every time it is killed on timeout. The pid is never
    registered anywhere, so this group is reachable only from inside this function;
    ``docket runs cancel`` cannot interrupt an in-flight verify command (see
    ``specs/functional/pod-dispatch.spec.md``'s Cancellation requirement 2)."""
    risk_cls = _sec.match_high_risk(cmd)
    if risk_cls is not None:
        return False, (
            f"[verify command refused: matches high-risk class '{risk_cls.name}' "
            f"({risk_cls.description}) -- see `docket setup sandbox classes`]"
        )
    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            cwd=cwd or None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            env=task_environment(env),
        )
    except (FileNotFoundError, OSError) as exc:
        return False, f"[verify error: {exc}]"
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        import contextlib
        import signal as _signal

        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, _signal.SIGKILL)
        with contextlib.suppress(subprocess.SubprocessError, OSError):
            proc.communicate(timeout=5)
        return False, f"[verify timed out after {timeout}s]"
    except OSError as exc:
        return False, f"[verify error: {exc}]"
    combined = (stdout + stderr).strip()
    return proc.returncode == 0, combined[:_VERIFY_MAX_OUTPUT]


def process_alive(pid: int) -> bool:
    """Whether a process with *pid* exists (signal 0 = probe only). A pid we may not signal
    still exists; a non-positive pid never does."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_group_alive(pgid: int) -> bool:
    """Best-effort liveness check for a process group (signal 0 = probe only)."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but we can't signal it — treat as alive (a real, distinct
        # failure mode from "already gone"; escalation below will hit the
        # same PermissionError and just stop trying, never crash the caller).
        return True
    return True


def kill_process_group(pgid: int, grace_s: float = 2.0) -> bool:
    """SIGTERM a process group; escalate to SIGKILL if still alive after
    *grace_s*. Requires the subprocess to have been started with
    ``start_new_session=True`` (pid doubles as process group id) -- a pid
    from anywhere else would signal an unrelated group, so callers must only
    pass one reported via a driver's ``on_spawn`` hook.

    Returns ``True`` if the group was observed alive (a signal was
    meaningfully sent), ``False`` if already gone -- a harmless no-op, not
    an error. Never raises: a process exiting mid-call is treated the same
    as one already gone."""
    import contextlib
    import signal as _signal

    if not _process_group_alive(pgid):
        return False
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, _signal.SIGTERM)
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline and _process_group_alive(pgid):
        time.sleep(0.05)
    if _process_group_alive(pgid):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, _signal.SIGKILL)
    return True


def git_available() -> bool:
    """Return True if a git binary is on PATH."""
    return _which("git")


def git_current_branch(cwd: str) -> str:
    """Return the current git branch for `cwd`, or '' if not a repo or unavailable; degrades
    gracefully on a missing binary, non-repo directory, or timeout. The ``diff_ref`` producer for an
    Implementer hop's ``HandoffArtifact`` (`core/dispatch.py`'s `_implementer_diff_probe`)."""
    if not git_available():
        return ""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def git_is_repo(cwd: str) -> bool:
    """Return True if ``cwd`` is inside a git repository."""
    if not git_available():
        return False
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def git_changed_files(cwd: str) -> list[str]:
    """Return paths with uncommitted changes in `cwd` (staged, unstaged,
    untracked); the `files_changed` producer for an Implementer hop's
    `HandoffArtifact`. Uses `git status --porcelain` (not a diff against a
    fixed base ref) so it reflects the real tree regardless of what the
    Implementer has committed this hop. Degrades to `[]` -- never raises --
    on a missing binary, non-repo directory, timeout, or clean tree. Sorted
    for determinism (porcelain order is otherwise platform-dependent)."""
    if not git_available():
        return []
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    files: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        # Porcelain v1: two status chars, a space, then the path. A rename/copy
        # line reads "R  old/path -> new/path" — keep only the new path.
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path.strip())
    return sorted(files)


def git_worktree_changes(cwd: str) -> list[tuple[str, str]]:
    """Return ``(status, absolute path)`` for every path ``git status`` reports in the repository
    containing `cwd`, untracked files listed one by one. Degrades to ``[]`` -- never raises --
    on a missing binary, non-repo directory, or timeout, like `git_changed_files`."""
    if not git_available():
        return []
    try:
        top = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )
        status = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain", "-z", "--untracked-files=all"],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if top.returncode != 0 or status.returncode != 0:
        return []
    root = top.stdout.strip()
    fields = status.stdout.split("\0")
    changes: list[tuple[str, str]] = []
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        # With -z a rename or copy is "XY new\0old\0": the original path is its own field.
        if code[0] in "RC":
            index += 1
        changes.append((code, os.path.join(root, path)))
    return changes


def git_worktree_fingerprint(cwd: str) -> dict[str, tuple[str, int, int]]:
    """Map every path `git_worktree_changes` reports to ``(status, size, mtime_ns)``, so two
    snapshots can tell a path that changed between them from one that merely stayed dirty. A
    path that no longer exists (a deletion) fingerprints as size and mtime ``-1``."""
    prints: dict[str, tuple[str, int, int]] = {}
    for code, path in git_worktree_changes(cwd):
        try:
            stat = os.stat(path)
            prints[path] = (code, stat.st_size, stat.st_mtime_ns)
        except OSError:
            prints[path] = (code, -1, -1)
    return prints


def git_worktree_add(repo_dir: str, worktree_path: str, branch: str) -> tuple[bool, str]:
    """Create a git worktree at ``worktree_path`` on a new branch ``branch``.
    Returns ``(success, error_message)``; degrades gracefully, returning
    ``(False, reason)`` on any error rather than raising."""
    if not git_available():
        return False, "git not found on PATH"
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "worktree", "add", "-b", branch, worktree_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, ""


def git_worktree_remove(repo_dir: str, worktree_path: str) -> tuple[bool, str]:
    """Remove the git worktree at ``worktree_path`` (``--force``, to handle
    unclean worktrees). Returns ``(success, message)``; degrades gracefully
    on errors."""
    if not git_available():
        return False, "git not found on PATH"
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "worktree", "remove", "--force", worktree_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, ""


def git_worktree_prune(repo_dir: str) -> None:
    """Drop worktree records whose directory is gone; silent on every error."""
    if not git_available():
        return
    with contextlib.suppress(subprocess.TimeoutExpired, OSError):
        subprocess.run(
            ["git", "-C", repo_dir, "worktree", "prune"],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )


def git_branch_merged(repo_dir: str, branch: str, into: str) -> bool:
    """True if ``branch`` is fully merged into ``into`` in ``repo_dir``; False on a missing
    binary, non-repo directory, timeout, or a genuinely unmerged branch."""
    if not git_available():
        return False
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "branch", "--merged", into],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    if result.returncode != 0:
        return False
    # "*" marks the current branch, "+" a branch checked out in another worktree.
    names = {line.strip().lstrip("*+ ").strip() for line in result.stdout.splitlines()}
    return branch in names


def git_branch_delete(repo_dir: str, branch: str) -> tuple[bool, str]:
    """Delete a local branch with ``-d`` (refuses an unmerged branch; never ``-D``).
    Returns ``(success, message)``; degrades gracefully on errors."""
    if not git_available():
        return False, "git not found on PATH"
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "branch", "-d", branch],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, ""


def git_head_sha(cwd: str) -> str | None:
    """Return the full 40-hex-char HEAD sha for `cwd`, or ``None`` if not a repo or
    unavailable; degrades gracefully like `git_current_branch`. The ``commit`` producer
    for an Implementer hop's persisted evidence."""
    if not git_available():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def git_merge_base(cwd: str, other_branch: str) -> str | None:
    """Return the merge-base sha of HEAD and `other_branch` in `cwd`, or ``None`` if not a
    repo, `other_branch` is unknown, or git is unavailable; degrades gracefully like
    `git_current_branch`. The ``baseCommit`` producer for an Implementer hop's evidence."""
    if not git_available():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "merge-base", "HEAD", other_branch],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


_SHORTSTAT_FILES = re.compile(r"(\d+) files? changed")
_SHORTSTAT_INSERTIONS = re.compile(r"(\d+) insertions?\(\+\)")
_SHORTSTAT_DELETIONS = re.compile(r"(\d+) deletions?\(-\)")


def git_diff_stat(cwd: str, base: str) -> dict[str, int] | None:
    """Return ``{"files", "insertions", "deletions"}`` diffing `base` against `cwd`'s current
    state (``git diff --shortstat``), or ``None`` if not a repo, `base` is missing, or git is
    unavailable; an empty summary (no changes) reports all-zero counts, not ``None``."""
    if not git_available():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "diff", "--shortstat", base],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    summary = result.stdout.strip()
    files_match = _SHORTSTAT_FILES.search(summary)
    insertions_match = _SHORTSTAT_INSERTIONS.search(summary)
    deletions_match = _SHORTSTAT_DELETIONS.search(summary)
    return {
        "files": int(files_match.group(1)) if files_match else 0,
        "insertions": int(insertions_match.group(1)) if insertions_match else 0,
        "deletions": int(deletions_match.group(1)) if deletions_match else 0,
    }
