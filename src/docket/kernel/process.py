"""The process port: the host tools docket shells out to, and the environment switches it reads live.

``secret-tool``, ``notify-send``, process groups and the ``DOCKET_*`` switches. The real adapter is
``platform.process``; ``bootstrap`` binds it, and a test binds ``tests.support.fakes.FakeProcess``
with ``use_process``.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from docket.kernel.binding import Binding

# Detection probes must be fast (they run on every "auto" call) and must never hang a tool call.
PROBE_TIMEOUT_S = 5


class Process(Protocol):
    def which(self, binary: str) -> bool:
        """Whether *binary* resolves on PATH (``False`` on any error)."""
        ...

    def secret_tool_available(self) -> bool: ...
    def desktop_notifications_available(self) -> bool: ...
    def secret_tool_lookup(self, service: str, key: str) -> str | None: ...
    def secret_tool_store(self, service: str, key: str, value: str) -> bool: ...
    def secret_tool_clear(self, service: str, key: str) -> bool: ...
    def make_non_dumpable(self) -> None: ...
    def process_alive(self, pid: int) -> bool: ...
    def kill_process_group(self, pgid: int, grace_s: float = 2.0) -> bool: ...
    def env_value(self, name: str) -> str: ...
    def credential_env_values(
        self, names: tuple[str, ...], suffixes: tuple[str, ...]
    ) -> list[str]: ...
    def secrets_backend_requested(self) -> str: ...
    def no_trace(self) -> bool: ...
    def no_export(self) -> bool: ...


_BINDING: Binding[Process] = Binding("process")
process: Process = _BINDING.proxy()


def bind_process(adapter: Process) -> None:
    _BINDING.bind(adapter)


def use_process(adapter: Process) -> AbstractContextManager[Process]:
    """Make *adapter* the process of this block (a test's fake)."""
    return _BINDING.use(adapter)
