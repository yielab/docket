"""Fixtures for the end-to-end lane: one world per test, built around that test's fake model."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from tests.support.e2e import World
from tests.support.model_server import FakeModel, fake_model

__all__ = ["fake_model", "world"]


@pytest.fixture()
def world(tmp_path: Path) -> Callable[..., World]:
    """A factory for the test's ``World``: ``world(model)`` or ``world(model, env={...})``."""

    def _build(model: FakeModel, *, env: Mapping[str, str] | None = None) -> World:
        return World(tmp_path / "world", model, env=env)

    return _build
