"""System."""

from __future__ import annotations

from docket.sandbox.landlock import landlock_argv


def run(cmd: list[str]) -> list[str]:
    return landlock_argv(cmd)
