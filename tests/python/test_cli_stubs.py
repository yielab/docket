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
    # M4 wave 2 — fully ported:
    # ["delete"],   # ported
    # ["wire"],     # ported
    # ["unwire"],   # ported
    # M4 wave 3a — fully ported:
    # ["edit"],     # ported
    # ["snapshot"], # ported
    # M4 wave 3b — fully ported:
    # ["logs"],     # ported
    # ["workflow"], # ported
    # M4 wave 3c — fully ported:
    # ["team"],     # ported
    # M4 final wave — fully ported:
    # ["add"],      # ported
    # ["maintain"], # ported
    # ["context"],  # ported
    # ["keys"],     # ported
    # ["auth"],     # ported
    ["doctor"],
    ["gates"],
    ["audit"],
    ["eval"],
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
