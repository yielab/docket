"""The audit log's home directory is created private (governance/audit.py)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from docket.governance import audit
from docket.kernel.home import Home, use_home

SUBJECT = "docket.governance.audit"


@pytest.fixture
def permissive_umask() -> Iterator[None]:
    old = os.umask(0o002)
    yield
    os.umask(old)


def test_a_fresh_home_directory_is_created_0700(tmp_path: Path, permissive_umask: None) -> None:
    home = tmp_path / "fresh-home"
    with use_home(Home(home)):
        assert audit.audit_log("pod.init").status == "written"
    assert oct(os.stat(home).st_mode & 0o777) == "0o700"
