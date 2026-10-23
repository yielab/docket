"""Dispatch."""

from __future__ import annotations


def ping() -> str:
    return "pong"


def claim_next(path: str) -> str:
    return path


def run_hop(path: str) -> str:
    return claim_next(path) + "!"
