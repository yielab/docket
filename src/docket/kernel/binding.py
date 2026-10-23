"""The one place a port finds its adapter.

A port is a ``Protocol`` in ``kernel`` plus a ``Binding`` for it. ``bootstrap`` binds the real
adapter once per entry (``bind``); a test swaps in a fake for a block (``use``), the same shape
``clock.use_clock`` gives the clock. ``proxy`` is the object callers import: it forwards each
attribute to whatever the binding holds at call time, so a caller keeps writing
``_git.git_head_sha(cwd)`` and never names an adapter.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Generic, TypeVar, cast

T = TypeVar("T")


class PortNotBound(RuntimeError):
    """A port was used before any entry bound an adapter to it."""


class Binding(Generic[T]):
    def __init__(self, name: str) -> None:
        self._name = name
        self._bound: T | None = None
        self._override: ContextVar[T | None] = ContextVar(f"docket_{name}_port", default=None)

    def bind(self, adapter: T) -> None:
        """Make *adapter* the process default; called by an entry point, never by a caller."""
        self._bound = adapter

    @contextmanager
    def use(self, adapter: T) -> Iterator[T]:
        """Make *adapter* the one of this block. Threads need ``kernel.threads`` to inherit it."""
        token = self._override.set(adapter)
        try:
            yield adapter
        finally:
            self._override.reset(token)

    def current(self) -> T:
        adapter = self._override.get() or self._bound
        if adapter is None:
            raise PortNotBound(
                f"the {self._name} port has no adapter: an entry point must call "
                "docket.bootstrap.bind_adapters() before it runs"
            )
        return adapter

    def proxy(self) -> T:
        return cast(T, _Proxy(self))


class _Proxy:
    def __init__(self, binding: Binding[Any]) -> None:
        self._binding = binding

    def __getattr__(self, name: str) -> object:
        return getattr(self._binding.current(), name)
