"""The codebase as it was at a task's base commit, for the files a prompt composes from it.

A task worktree is writable by the Implementer, so an ``AGENTS.md`` or ``.docket/skills`` file
read from it can be rewritten by the very hop whose work the next hop reviews. A ``RepoView``
is the injected reader that serves those files from the base commit instead; the git read behind
it lives in ``edges/`` and this module never shells out. A view is registered for one worktree
root for the length of a turn, in that turn's context only, and ``core/identity.py`` and
``core/skills.py`` consult ``view_for(root)`` before touching the filesystem. ``composed`` records the sha256 of the bytes
each file served, keyed by repository-relative path."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Mapping
from contextvars import ContextVar, Token
from pathlib import Path
from types import MappingProxyType


class RepoView:
    """Reads repository-relative paths at one commit through two injected readers."""

    def __init__(
        self,
        commit: str,
        read_blob: Callable[[str], bytes | None],
        list_dirs: Callable[[str], list[str] | None],
    ) -> None:
        self.commit = commit
        self._read_blob = read_blob
        self._list_dirs = list_dirs
        self.composed: dict[str, str] = {}
        self._blobs: dict[str, bytes | None] = {}
        self._dirs: dict[str, list[str]] = {}

    def read(self, rel: str) -> bytes | None:
        """The bytes at *rel*, or ``None`` when absent at the commit; one git read per path for the
        view's lifetime. Records their sha256."""
        if rel in self._blobs:
            return self._blobs[rel]
        data = self._read_blob(rel)
        self._blobs[rel] = data
        if data is not None:
            self.composed[rel] = hashlib.sha256(data).hexdigest()
        return data

    def read_text(self, rel: str) -> str | None:
        data = self.read(rel)
        return None if data is None else data.decode("utf-8", errors="replace")

    def is_file(self, rel: str) -> bool:
        """Whether *rel* is a blob at the commit (reading it, so it is recorded as served)."""
        return self.read(rel) is not None

    def list_dirs(self, rel: str) -> list[str]:
        if rel not in self._dirs:
            self._dirs[rel] = self._list_dirs(rel) or []
        return self._dirs[rel]


# Context-local, not module-global: the children of a ``parallel`` group run concurrently in
# one worktree, each in its own copied context (``orchestrator.run_group``), so one child ending
# its turn never removes the view a sibling is still reading through.
_VIEWS: ContextVar[Mapping[str, RepoView]] = ContextVar(
    "docket_repo_views", default=MappingProxyType({})
)


def _key(root: Path | str) -> str:
    return os.path.realpath(root)


def register(root: Path | str, view: RepoView) -> Token[Mapping[str, RepoView]]:
    """Serve *root*'s files through *view* in this context until ``unregister(token)``."""
    return _VIEWS.set({**_VIEWS.get(), _key(root): view})


def unregister(token: Token[Mapping[str, RepoView]]) -> None:
    _VIEWS.reset(token)


def view_for(root: Path | str | None) -> RepoView | None:
    """The view registered for *root* in this context, or ``None`` (read the filesystem)."""
    return None if root is None else _VIEWS.get().get(_key(root))
