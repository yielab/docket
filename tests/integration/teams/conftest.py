"""Fixtures shared by the pod memory integration files."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.pod_memory import make_repo


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    """A repository with one commit and its sha."""
    return make_repo(tmp_path)
