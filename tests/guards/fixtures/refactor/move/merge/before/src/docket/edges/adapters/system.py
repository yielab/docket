"""System."""

from __future__ import annotations


def landlock_argv(cmd: list[str]) -> list[str]:
    return cmd


def run(cmd: list[str]) -> list[str]:
    return landlock_argv(cmd)
