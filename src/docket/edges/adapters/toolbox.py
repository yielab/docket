"""Built-in tool implementations (ROADMAP Phase 19 P19-2 / D-19).

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
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Tool output is fed straight back into a model's context, so an unbounded
# result is a context-budget failure waiting to happen (and, for `bash`, a way
# to blow the window with one `find /`). Truncation is always announced in the
# returned text — silently short output would be read as "that is all there is".
MAX_OUTPUT_CHARS = 30_000
MAX_GREP_MATCHES = 200
MAX_GLOB_RESULTS = 300


class PathEscapeError(ValueError):
    """A tool was asked to touch a path outside every allowed root."""


@dataclass
class ToolOutcome:
    """What happened when a tool ran. Not whether it was allowed to."""

    ok: bool
    content: str = ""
    error: str = ""


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
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


def run_bash(
    roots: tuple[Path, ...],
    command: str,
    timeout: int = 120,
    env: dict[str, str] | None = None,
) -> ToolOutcome:
    """Run *command* in a shell, rooted at the first allowed root.

    **This function performs no gating.** It is reached only after
    ``core/tools.py`` has classified the command and, where required, obtained
    approval. Started in its own session so a timeout can kill the whole
    process group — a shell command that spawns children and then hangs is the
    normal case, not the exotic one, and killing only the shell orphans them.
    """
    if not roots:
        return ToolOutcome(False, error="no working directory configured")
    cwd = roots[0].resolve()
    run_env = {**os.environ, **env} if env else None
    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=run_env,
            start_new_session=True,
        )
    except OSError as ex:
        return ToolOutcome(False, error=f"cannot start command: {ex}")

    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        return ToolOutcome(False, error=f"command timed out after {timeout}s")

    body = _truncate((out or "").strip())
    if proc.returncode != 0:
        return ToolOutcome(
            False,
            content=body,
            error=f"command exited {proc.returncode}",
        )
    return ToolOutcome(True, content=body or "(no output)")


def _kill_group(proc: subprocess.Popen[str]) -> None:
    """Kill a timed-out command's whole process group, then reap it."""
    import contextlib
    import signal

    with contextlib.suppress(OSError, ProcessLookupError):
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    with contextlib.suppress(subprocess.SubprocessError, OSError):
        proc.communicate(timeout=5)
