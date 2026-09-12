"""Built-in tool implementations.

The side-effecting half of docket's tool set: the code that actually reads a
file, writes one, or runs a command. It is deliberately dumb — every one of
these functions assumes the decision to run it has already been made and
recorded by ``core/tools.py``'s chokepoint. **Nothing here consults a policy,
an allowlist or an approval store**, because a second module that could decide
to execute something is a second place a gate can be forgotten.

The one exception, and it is containment rather than policy: every path is
resolved against a set of allowed roots before it is touched, and a path that
escapes them raises. That check lives here because it needs the real
filesystem (symlinks resolve, ``..`` collapses) and because it must hold no
matter which caller arrives — a containment rule enforced only at the
chokepoint would be one refactor away from being bypassed.

Layering: this module imports nothing from ``core/``. It reports what happened
via a local ``ToolOutcome``; ``core/tools.py`` wraps that with what was
*decided*.

``run_bash``'s ``sandbox`` parameter is the one
addition to that contract, and it is still mechanism, not policy -- it does
not decide *whether* a command may run (that is ``core/tools.py``'s gate,
already applied by the time this function is ever called); it decides, once
a command is already cleared to run, *what it can reach while it does*. The
gate is not a sandbox, and this module's containment story was never a
substitute for one either -- ``resolve_within`` only ever checked path
*arguments* the file tools were given; a `bash` command's shell text was
never checked against it at all, and still is not -- sandboxing constrains
the running process instead, additively, never in place of that check.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import docket.config as _cfg
from docket.edges.adapters import system as _system
from docket.edges.adapters.system import SandboxAvailability, SandboxBackend

SandboxMode = Literal["off", "auto"]

# Tool output is fed straight back into a model's context, so an unbounded
# result is a context-budget failure waiting to happen (and, for `bash`, a way
# to blow the window with one `find /`). Truncation is always announced in the
# returned text — silently short output would be read as "that is all there is".
# The value is config.py's (DOCKET_TOOL_MAX_OUTPUT_CHARS) because the usable
# ceiling depends on the endpoint's context window, not on this module.
MAX_OUTPUT_CHARS = _cfg.TOOL_MAX_OUTPUT_CHARS
MAX_GREP_MATCHES = 200
MAX_GLOB_RESULTS = 300

# How often `run_bash`'s cancellable wait loop re-checks the callback and the
# overall deadline. Short enough that a separate process's cancellation
# request is noticed well inside any caller's patience; long enough that
# idle polling costs nothing measurable.
_CANCEL_POLL_INTERVAL_S = 0.1


class PathEscapeError(ValueError):
    """A tool was asked to touch a path outside every allowed root."""


@dataclass
class ToolOutcome:
    """What happened when a tool ran. Not whether it was allowed to."""

    ok: bool
    content: str = ""
    error: str = ""


def _truncate(text: str, limit: int | None = None) -> str:
    # Resolved per call, not bound as a default argument, so the ceiling stays
    # a live setting rather than whatever it happened to be at import time.
    limit = MAX_OUTPUT_CHARS if limit is None else limit
    if len(text) <= limit:
        return text
    dropped = len(text) - limit
    return f"{text[:limit]}\n\n[truncated: {dropped} more characters]"


def resolve_within(roots: tuple[Path, ...], candidate: str) -> Path:
    """Resolve *candidate* and confirm it lives under one of *roots*.

    Relative paths resolve against the first root (the agent's workspace).
    ``resolve()`` is called on both sides, so ``..`` traversal and symlinks out
    of the tree are caught rather than merely discouraged.

    Raises ``PathEscapeError`` when the path is outside every root, and when
    *roots* is empty — an unrooted call is a caller bug, and defaulting to
    "anywhere" would turn it into a security hole.
    """
    if not roots:
        raise PathEscapeError("no allowed roots configured for this tool call")
    raw = Path(candidate).expanduser()
    target = raw if raw.is_absolute() else roots[0] / raw
    resolved = target.resolve()
    for root in roots:
        root_resolved = root.resolve()
        if resolved == root_resolved or root_resolved in resolved.parents:
            return resolved
    allowed = ", ".join(str(r) for r in roots)
    raise PathEscapeError(f"{candidate!r} resolves outside the allowed roots ({allowed})")


# ── file tools ────────────────────────────────────────────────────────────────


def read_file(roots: tuple[Path, ...], path: str, offset: int = 0, limit: int = 0) -> ToolOutcome:
    """Read a text file, optionally a line window of it (1-indexed *offset*)."""
    try:
        target = resolve_within(roots, path)
    except PathEscapeError as ex:
        return ToolOutcome(False, error=str(ex))
    if not target.is_file():
        return ToolOutcome(False, error=f"not a file: {path}")
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as ex:
        return ToolOutcome(False, error=f"cannot read {path}: {ex}")

    if offset or limit:
        lines = text.splitlines()
        start = max(0, offset - 1) if offset else 0
        end = start + limit if limit else len(lines)
        text = "\n".join(lines[start:end])
    return ToolOutcome(True, content=_truncate(text))


def write_file(roots: tuple[Path, ...], path: str, content: str) -> ToolOutcome:
    """Create or overwrite a text file, creating parent directories."""
    try:
        target = resolve_within(roots, path)
    except PathEscapeError as ex:
        return ToolOutcome(False, error=str(ex))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as ex:
        return ToolOutcome(False, error=f"cannot write {path}: {ex}")
    return ToolOutcome(True, content=f"wrote {len(content)} characters to {target}")


def edit_file(
    roots: tuple[Path, ...],
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> ToolOutcome:
    """Replace *old_string* with *new_string* in a file.

    A non-unique match fails rather than guessing which occurrence was meant —
    the same contract docket's own editing tools use, and for the same reason:
    an edit applied to the wrong occurrence is worse than an edit refused.
    """
    try:
        target = resolve_within(roots, path)
    except PathEscapeError as ex:
        return ToolOutcome(False, error=str(ex))
    if not target.is_file():
        return ToolOutcome(False, error=f"not a file: {path}")
    if not old_string:
        return ToolOutcome(False, error="old_string must not be empty")
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as ex:
        return ToolOutcome(False, error=f"cannot read {path}: {ex}")

    occurrences = text.count(old_string)
    if occurrences == 0:
        return ToolOutcome(False, error=f"old_string not found in {path}")
    if occurrences > 1 and not replace_all:
        return ToolOutcome(
            False,
            error=(
                f"old_string appears {occurrences} times in {path}; "
                "pass replace_all or include more surrounding context"
            ),
        )
    updated = (
        text.replace(old_string, new_string)
        if replace_all
        else text.replace(old_string, new_string, 1)
    )
    try:
        target.write_text(updated, encoding="utf-8")
    except OSError as ex:
        return ToolOutcome(False, error=f"cannot write {path}: {ex}")
    replaced = occurrences if replace_all else 1
    return ToolOutcome(True, content=f"replaced {replaced} occurrence(s) in {target}")


def glob_files(roots: tuple[Path, ...], pattern: str, path: str = "") -> ToolOutcome:
    """List files matching a glob *pattern*, newest first."""
    try:
        base = resolve_within(roots, path) if path else roots[0].resolve()
    except (PathEscapeError, IndexError) as ex:
        return ToolOutcome(False, error=str(ex))
    if not base.is_dir():
        return ToolOutcome(False, error=f"not a directory: {path or base}")
    try:
        matches = [p for p in base.glob(pattern) if p.is_file()]
    except (OSError, ValueError) as ex:
        return ToolOutcome(False, error=f"bad glob {pattern!r}: {ex}")
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    shown = matches[:MAX_GLOB_RESULTS]
    body = "\n".join(str(p) for p in shown) or "(no matches)"
    if len(matches) > len(shown):
        body += f"\n\n[truncated: {len(matches) - len(shown)} more matches]"
    return ToolOutcome(True, content=body)


def grep_files(
    roots: tuple[Path, ...], pattern: str, path: str = "", glob: str = "**/*"
) -> ToolOutcome:
    """Search file contents for a regex, returning ``path:line:text`` hits.

    Implemented in Python rather than shelling out to ``rg``/``grep`` on
    purpose: a tool that quietly degrades when a binary is missing would give
    different answers on different machines, and routing it through the shell
    would put a second exec path next to the gated one.
    """
    try:
        base = resolve_within(roots, path) if path else roots[0].resolve()
    except (PathEscapeError, IndexError) as ex:
        return ToolOutcome(False, error=str(ex))
    try:
        regex = re.compile(pattern)
    except re.error as ex:
        return ToolOutcome(False, error=f"bad regex {pattern!r}: {ex}")

    hits: list[str] = []
    truncated = False
    for candidate in sorted(base.glob(glob)):
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                hits.append(f"{candidate}:{lineno}:{line.strip()[:300]}")
                if len(hits) >= MAX_GREP_MATCHES:
                    truncated = True
                    break
        if truncated:
            break

    body = "\n".join(hits) or "(no matches)"
    if truncated:
        body += f"\n\n[truncated at {MAX_GREP_MATCHES} matches]"
    return ToolOutcome(True, content=_truncate(body))


# ── exec ──────────────────────────────────────────────────────────────────────


def _jailed_env(env: dict[str, str] | None) -> dict[str, str]:
    """Minimal environment for a real (non-``"none"``) sandboxed run: PATH
    plus whatever the caller explicitly asked to inject (e.g.
    ``DOCKET_SCRATCH_DIR``). Deliberately **not** the full host environment
    ``run_bash``'s unsandboxed path uses -- forwarding it wholesale into a
    jail would hand a "sandboxed" command every credential the unsandboxed
    path has anyway, which is precisely the reach this backend exists to
    cut down, not preserve.
    """
    minimal = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    if env:
        minimal.update(env)
    return minimal


def _sandbox_tag(sandbox: SandboxMode, availability: SandboxAvailability | None) -> str:
    """The honest, per-call answer to "was this actually sandboxed, and by
    what" -- ``""`` when nobody asked (``sandbox="off"``, the default;
    ``run_bash``'s original, unsandboxed behaviour is untouched, byte for
    byte, in that case). When asked (``sandbox="auto"``), always says what
    really happened, including ``"none (...)"`` when neither backend panned
    out. A jailed-looking result that was not actually jailed is precisely
    the failure this card exists to prevent, so this never stays silent
    once asked.
    """
    if sandbox != "auto" or availability is None:
        return ""
    if availability.backend != "none":
        return f"sandbox: {availability.backend}"
    reasons = [
        reason
        for ok, reason in (
            (availability.docker, "docker unavailable"),
            (availability.bwrap, "bwrap unavailable"),
        )
        if not ok
    ]
    if not reasons:
        # Both backends actually checked out usable -- "none" here can only
        # mean DOCKET_SANDBOX_BACKEND=none forced it. Say that plainly rather
        # than print an empty, unexplained "()".
        reasons = ["forced off via DOCKET_SANDBOX_BACKEND"]
    return f"sandbox: none ({', '.join(reasons)})"


def run_bash(
    roots: tuple[Path, ...],
    command: str,
    timeout: int = 120,
    env: dict[str, str] | None = None,
    sandbox: SandboxMode = "off",
    cancelled: Callable[[], bool] | None = None,
) -> ToolOutcome:
    """Run *command* in a shell, rooted at the first allowed root.

    **This function performs no gating.** It is reached only after
    ``core/tools.py`` has classified the command and, where required, obtained
    approval. Started in its own session so a timeout can kill the whole
    process group — a shell command that spawns children and then hangs is the
    normal case, not the exotic one, and killing only the shell orphans them.

    ``sandbox`` is opt-in and defaults to ``"off"`` — with it, this function
    behaves exactly as it always has, byte for byte. ``"auto"`` asks for the
    strongest exec jail this host actually has *right now*
    (``edges.adapters.system.sandbox_availability``, resolved fresh on every
    call rather than cached from install time) and reports which one it got —
    including ``"none"``, when neither docker nor bwrap panned out — as a
    trailing ``[sandbox: ...]`` marker on the result. **This function never
    decides whether to ask for a jail; it only reports, honestly, what
    happened once asked.** A jail that was requested but failed to even start
    is reported as a failure, never silently retried unsandboxed — the one
    failure mode worse than no sandbox is one that is claimed and absent.

    ``cancelled`` is the one seam that lets a separate process interrupt this
    command mid-run. Every other tool handler simply runs to completion once
    started, because a Python thread cannot be killed safely — a subprocess
    can. Left at its default ``None``, this function is unchanged, byte for
    byte, including the timeout message: a caller that never passes it sees
    exactly today's behaviour. Given a callback, a short bounded poll (still
    honouring *timeout*) checks it between waits, and a true result kills the
    process group exactly as a timeout already does (``system.docker_kill``
    under the docker backend, then ``_kill_group``), returning a complete
    cancelled ``ToolOutcome`` rather than leaving the caller to wait out the
    tool's own timeout.
    """
    if not roots:
        return ToolOutcome(False, error="no working directory configured")
    cwd = roots[0].resolve()

    availability = _system.sandbox_availability() if sandbox == "auto" else None
    backend: SandboxBackend = availability.backend if availability else "none"
    tag = _sandbox_tag(sandbox, availability)

    popen_env: dict[str, str] | None
    container_name = ""
    if backend == "docker":
        container_name = f"docket-sbx-{uuid.uuid4().hex[:12]}"
        popen_arg: str | list[str] = _system.docker_run_argv(container_name, roots, command, env)
        shell = False
        popen_env = None  # the CLI inherits; the container gets only `env`, via -e flags in argv
    elif backend == "bwrap":
        popen_arg = _system.bwrap_argv(roots, command)
        shell = False
        popen_env = _jailed_env(env)
    else:
        popen_arg = command
        shell = True
        popen_env = {**os.environ, **env} if env else None

    try:
        proc = subprocess.Popen(
            popen_arg,
            shell=shell,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=popen_env,
            start_new_session=True,
        )
    except OSError as ex:
        if backend != "none":
            return ToolOutcome(False, error=f"sandbox ({backend}) failed to start: {ex}")
        return ToolOutcome(False, error=f"cannot start command: {ex}")

    if cancelled is None:
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if backend == "docker":
                _system.docker_kill(container_name)
            _kill_group(proc)
            message = f"command timed out after {timeout}s"
            return ToolOutcome(False, error=f"{message} [{tag}]" if tag else message)
    else:
        timed_out, was_cancelled, out = _wait_cancellable(proc, timeout, cancelled)
        if timed_out or was_cancelled:
            if backend == "docker":
                _system.docker_kill(container_name)
            _kill_group(proc)
            message = (
                "cancelled before completion"
                if was_cancelled
                else f"command timed out after {timeout}s"
            )
            return ToolOutcome(False, error=f"{message} [{tag}]" if tag else message)

    body = _truncate((out or "").strip())
    if proc.returncode != 0:
        message = f"command exited {proc.returncode}"
        return ToolOutcome(
            False,
            content=body,
            error=f"{message} [{tag}]" if tag else message,
        )
    content = body or "(no output)"
    return ToolOutcome(True, content=f"{content}\n\n[{tag}]" if tag else content)


# A bare `proc.wait()` never drains stdout, so a command that writes more
# than the OS pipe buffer (commonly 64KB) blocks on its own next write and
# never actually exits -- indistinguishable from a hang to a poll loop that
# only checks exit status. A background reader draining the pipe in parallel
# is what `communicate()` already does internally; this must keep doing it
# too, or a real build/test/verbose command loses its output to a false
# timeout the instant a cancellation callback is merely present, whether or
# not it ever fires.
def _wait_cancellable(
    proc: subprocess.Popen[str], timeout: int, cancelled: Callable[[], bool]
) -> tuple[bool, bool, str]:
    """Wait for *proc* to exit, checking *cancelled* between short polls.

    Returns ``(timed_out, was_cancelled, output)`` — at most one of the first two is true."""
    assert proc.stdout is not None
    drained: list[str] = []

    def _drain() -> None:
        import contextlib

        with contextlib.suppress(OSError, ValueError):
            drained.append(proc.stdout.read())  # type: ignore[union-attr]

    reader = threading.Thread(target=_drain, daemon=True)
    reader.start()

    deadline = time.monotonic() + timeout
    while True:
        if not reader.is_alive():
            reader.join()
            proc.wait()
            return False, False, drained[0] if drained else ""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True, False, ""
        if cancelled():
            return False, True, ""
        time.sleep(max(0.0, min(_CANCEL_POLL_INTERVAL_S, remaining)))


def _kill_group(proc: subprocess.Popen[str]) -> None:
    """Kill a timed-out command's whole process group, then reap it.

    Holds under every sandbox backend this module supports, not just the
    unsandboxed path: bwrap's own process (started with
    ``start_new_session=True`` here, same as the plain case) stays in that
    process group, so this reaches it and everything it forked, and Linux
    additionally tears down bwrap's entire pid namespace the moment its
    first process dies — a command inside it cannot escape by detaching
    (verified: test_sandboxed_exec.py's bwrap orphan test). Docker is
    the one shape this does *not* cover on its own: ``docker run``'s CLI
    process is a thin client the daemon runs the real container under, so
    killing its process group alone leaves the container running (verified
    the same way) — ``run_bash``'s timeout handler calls
    ``system.docker_kill`` first, specifically because this function cannot
    reach a docker-jailed command by process group at all.
    """
    import contextlib
    import signal

    with contextlib.suppress(OSError, ProcessLookupError):
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    with contextlib.suppress(subprocess.SubprocessError, OSError):
        proc.communicate(timeout=5)
