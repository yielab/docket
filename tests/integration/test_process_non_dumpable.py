"""A child of a docket process cannot read the parent's environment through /proc.

A real subprocess pair is the boundary: the helper must never run inside the pytest process,
because it would change pytest's own dumpability for the rest of the run.
See specs/functional/security-gates.spec.md "Credentials in task processes" item 4.

LANE: integration
REASON: names a real process boundary (a parent and its same-uid child)
RETIRE_WHEN: never; it pins the credential-isolation contract
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

SUBJECT = "docket.edges.adapters.system"

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux /proc only")

_PARENT = textwrap.dedent(
    """
    import subprocess, sys
    from docket.edges.adapters import system
    if sys.argv[1] == "harden":
        system.make_non_dumpable()
    child = (
        "import os\\n"
        "try:\\n"
        "    data = open('/proc/%d/environ' % os.getppid(), 'rb').read()\\n"
        "    print('READ' if b'FAKE_SEEDED_KEY' in data else 'EMPTY')\\n"
        "except PermissionError:\\n"
        "    print('DENIED')\\n"
    )
    out = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True)
    print(out.stdout.strip())
    """
)


def _run(mode: str) -> str:
    env = {"PATH": "/usr/bin:/bin", "DOCKET_LLM_API_KEY": "FAKE_SEEDED_KEY"}
    proc = subprocess.run(
        [sys.executable, "-c", _PARENT, mode],
        capture_output=True,
        text=True,
        env={**env, "PYTHONPATH": ":".join(sys.path)},
        timeout=60,
    )
    return proc.stdout.strip()


def test_unhardened_parent_environment_is_readable_by_a_child() -> None:
    """Control: without the helper the child reads the seeded key."""
    assert _run("plain") == "READ"


def test_hardened_parent_environment_is_denied_to_a_child() -> None:
    """After make_non_dumpable the child gets PermissionError."""
    assert _run("harden") == "DENIED"
