"""The `command` and `console` delivery dialects (`edges/adapters/channels/command.py`,
`edges/adapters/channels/console.py`), plus `sink_for`'s dialect lookup
(`edges/adapters/channels/__init__.py`).
"""

from __future__ import annotations

import json
import sys
from typing import Any

from docket.core.operator_contract import make_event
from docket.edges.adapters import channels
from docket.edges.adapters.channels import command, console

SUBJECT = "docket.edges.adapters.channels.command"


class _ChannelSpecLike:
    def __init__(self, config: dict[str, str]) -> None:
        self.config = config


def _event() -> Any:
    return make_event(
        "task.completed",
        "alpha",
        "task:alpha:t1",
        {"pod": "alpha", "taskId": "t1"},
        time="2026-09-28T00:00:00Z",
        version="done:",
    )


_ECHO_STDIN = [sys.executable, "-c", "import sys; sys.stdin.read()"]
_FAIL = [sys.executable, "-c", "import sys; sys.exit(3)"]


class TestCommandDeliver:
    def test_argv_json_list_runs_and_succeeds(self) -> None:
        spec = _ChannelSpecLike({"argv": json.dumps(_ECHO_STDIN)})
        result = command.deliver(spec, _event(), secret=None, timeout=5.0)
        assert result.ok is True
        assert result.status == 0

    def test_plain_command_key_is_a_single_element_argv(self) -> None:
        spec = _ChannelSpecLike({"command": sys.executable})
        # bare python with no args just starts a REPL reading stdin; giving it -c via argv
        # isn't possible through a single bare path, so assert only that it ran (exit 0 on
        # EOF) rather than depending on any particular behaviour of the interpreter itself.
        result = command.deliver(spec, _event(), secret=None, timeout=5.0)
        assert result.status == 0

    def test_nonzero_exit_is_a_failure(self) -> None:
        spec = _ChannelSpecLike({"argv": json.dumps(_FAIL)})
        result = command.deliver(spec, _event(), secret=None, timeout=5.0)
        assert result.ok is False
        assert result.status == 3

    def test_missing_argv_and_command_never_raises(self) -> None:
        spec = _ChannelSpecLike({})
        result = command.deliver(spec, _event(), secret=None, timeout=5.0)
        assert result.ok is False
        assert "argv" in result.error or "command" in result.error

    def test_missing_binary_never_raises(self) -> None:
        spec = _ChannelSpecLike({"argv": json.dumps(["/no/such/binary-xyz"])})
        result = command.deliver(spec, _event(), secret=None, timeout=5.0)
        assert result.ok is False
        assert result.error


class TestConsoleDeliver:
    def test_always_succeeds_without_sending_anything(self) -> None:
        result = console.deliver(_ChannelSpecLike({}), _event(), secret=None, timeout=5.0)
        assert result.ok is True


class TestSinkFor:
    def test_known_dialects_resolve(self) -> None:
        for dialect, module in (("console", console), ("command", command)):
            spec = _ChannelSpecLike({})
            spec.dialect = dialect  # type: ignore[attr-defined]
            assert channels.sink_for(spec) is module.deliver

    def test_newly_wired_dialects_resolve(self) -> None:
        from docket.edges.adapters.channels import desktop, email, ntfy

        for dialect, module in (("ntfy", ntfy), ("desktop", desktop), ("email", email)):
            spec = _ChannelSpecLike({})
            spec.dialect = dialect  # type: ignore[attr-defined]
            assert channels.sink_for(spec) is module.deliver

    def test_unknown_dialect_returns_none(self) -> None:
        spec = _ChannelSpecLike({})
        spec.dialect = "unknown_dialect"  # type: ignore[attr-defined]
        assert channels.sink_for(spec) is None
