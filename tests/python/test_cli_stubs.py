"""M1 smoke tests: every command stub exits 127 (not-ported signal)."""

import subprocess
import sys

import pytest

COMMANDS = [
    # M3 — fully ported, no longer exit 127:
    # ["list"],  # ported
    # ["info"],  # ported
    # ["cost"],  # ported
    # M4 wave 1 — fully ported:
    # ["profile"],  # ported
    # ["scope"],    # ported
    # ["models"],   # ported
    ["add"],
    ["delete"],
    ["maintain"],
    ["context"],
    ["wire"],
    ["unwire"],
    ["keys"],
    ["auth"],
    ["team"],
    ["workflow"],
    ["logs"],
    ["edit"],
    ["doctor"],
    ["gates"],
    ["audit"],
    ["eval"],
    ["snapshot"],
    ["serve"],
    ["completions"],
    ["trace"],
    ["metrics"],
    ["policies"],
    ["approve"],
    ["deny"],
    ["help"],
    ["install"],
]


@pytest.mark.parametrize("cmd", COMMANDS, ids=[c[0] for c in COMMANDS])
def test_stub_exits_127(cmd: list[str]) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "docket", *cmd],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 127, (
        f"Expected 127 (not-ported) for `docket {' '.join(cmd)}`, "
        f"got {result.returncode}.\nstderr: {result.stderr}"
    )
    assert "not yet ported" in result.stderr
