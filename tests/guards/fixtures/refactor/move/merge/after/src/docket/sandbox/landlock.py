"""Landlock."""

from __future__ import annotations


def landlock_ok() -> bool:
    return True


def landlock_argv(cmd: list[str]) -> list[str]:
    return cmd
