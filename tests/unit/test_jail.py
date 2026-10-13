"""The jail entry's argument handling and fail-closed exits, with the kernel layer replaced."""

from __future__ import annotations

import pytest

from docket import jail
from docket.edges.adapters import landlock

SUBJECT = "docket.jail"


def test_no_command_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert jail.main(["--rw", "/x", "--"]) == jail.EXIT_REFUSED
    assert "no command" in capsys.readouterr().err


def test_an_unenforceable_jail_runs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[list[str]] = []
    monkeypatch.setattr(landlock, "abi_version", lambda: 0)
    monkeypatch.setattr(jail.os, "execvp", lambda f, a: ran.append(a))
    assert jail.main(["--net", "none", "--", "true"]) == jail.EXIT_REFUSED
    assert ran == []


def test_the_confinement_is_applied_before_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(landlock, "abi_version", lambda: 5)
    monkeypatch.setattr(landlock, "no_new_privs", lambda: calls.append("nnp"))
    monkeypatch.setattr(landlock, "install_socket_filter", lambda p: calls.append("seccomp"))
    monkeypatch.setattr(landlock, "enforce", lambda plan: calls.append("landlock"))
    monkeypatch.setattr(jail.os, "execvp", lambda f, a: calls.append(f"exec {a}"))
    jail.main(["--rw", "/work", "--net", "none", "--", "echo", "hi"])
    assert calls[:3] == ["nnp", "seccomp", "landlock"]
    assert calls[3] == "exec ['echo', 'hi']"


def test_net_open_installs_no_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(landlock, "abi_version", lambda: 5)
    monkeypatch.setattr(landlock, "no_new_privs", lambda: calls.append("nnp"))
    monkeypatch.setattr(landlock, "install_socket_filter", lambda p: calls.append("seccomp"))
    monkeypatch.setattr(landlock, "enforce", lambda plan: calls.append("landlock"))
    monkeypatch.setattr(jail.os, "execvp", lambda f, a: None)
    jail.main(["--net", "open", "--", "true"])
    assert calls == ["nnp", "landlock"]
