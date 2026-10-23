"""Guard: only a typed command re-reads a repository's `.docket/`; dispatch never does.

`docket start` and `dispatch_pod` must not reach the repository re-read or the
operator's review store (ADR 0012 and 0024), pinned by the names each module references.
"""

from __future__ import annotations

import ast
from pathlib import Path

import docket

_SRC = Path(docket.__file__).parent
_FORBIDDEN = {"repo_changes", "classify_directory", "plan_apply", "reviewed_repos"}
# Dispatch is the tasks, hops and pipeline contexts; `docket start` is the HTTP server and the
# service command.
_UNREAD_DIRS = ("tasks", "hops", "pipeline", "interfaces/http")
_UNREAD = (
    *(
        p.relative_to(_SRC).as_posix()
        for d in _UNREAD_DIRS
        for p in sorted((_SRC / d).rglob("*.py"))
    ),
    "interfaces/cli/commands/service.py",
)


def _names(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            found.update(a.name for a in node.names)
            found.add((node.module or "").rsplit(".", 1)[-1])
        elif isinstance(node, ast.Import):
            found.update(a.name.rsplit(".", 1)[-1] for a in node.names)
    return found


def test_no_dispatch_path_reads_the_repository_or_its_review() -> None:
    offenders = {rel: sorted(_names(_SRC / rel) & _FORBIDDEN) for rel in _UNREAD}
    assert {rel: hit for rel, hit in offenders.items() if hit} == {}


def test_the_typed_run_command_does() -> None:
    assert "repo_changes" in _names(_SRC / "interfaces" / "cli" / "commands" / "run.py")
