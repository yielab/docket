"""Threads that run in the context of the code that started them.

``current_home()`` and the test clock read a ``ContextVar``, and a new thread starts with an
empty context, so a bare ``threading.Thread`` would fall back to the process default home. Every
thread docket starts goes through here instead, so it sees the home, clock and run it was
started under. The context is copied when the thread is built, not when it first runs.
"""

from __future__ import annotations

import contextvars
import socket
import threading
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import Executor, Future
from http.server import ThreadingHTTPServer
from typing import Any


def new_thread(
    target: Callable[..., object],
    args: Iterable[Any] = (),
    kwargs: Mapping[str, Any] | None = None,
    *,
    name: str | None = None,
    daemon: bool = True,
) -> threading.Thread:
    """An unstarted daemon thread whose *target* runs in a copy of the caller's context."""
    ctx = contextvars.copy_context()
    return threading.Thread(
        target=ctx.run, args=(target, *args), kwargs=dict(kwargs or {}), name=name, daemon=daemon
    )


def start_thread(
    target: Callable[..., object],
    args: Iterable[Any] = (),
    kwargs: Mapping[str, Any] | None = None,
    *,
    name: str | None = None,
    daemon: bool = True,
) -> threading.Thread:
    """`new_thread`, started."""
    thread = new_thread(target, args, kwargs, name=name, daemon=daemon)
    thread.start()
    return thread


def submit(pool: Executor, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future[Any]:
    """``pool.submit`` with *fn* run in a copy of the context at the call."""
    return pool.submit(contextvars.copy_context().run, fn, *args, **kwargs)


class ContextHTTPServer(ThreadingHTTPServer):
    """A threading HTTP server whose request threads run in the context it was built in.

    Each request gets its own copy, because one context cannot be entered by two threads."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._built_in = contextvars.copy_context()
        super().__init__(*args, **kwargs)

    def process_request_thread(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: Any
    ) -> None:
        self._built_in.copy().run(super().process_request_thread, request, client_address)
