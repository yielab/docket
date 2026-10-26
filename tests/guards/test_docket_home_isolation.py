"""The test suite must never read or write the developer's real ``~/.docket``.

``conftest.py``'s ``_isolate_docket_home`` autouse fixture is the fix; this
module is the guard that keeps it honest.

Some paths have no environment override at all, so an individual test cannot opt out
of the real path even deliberately. That is precisely why isolation must be
an autouse default rather than each test's own responsibility, and why this
guard asserts on every path the home hands out rather than a sample.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from docket.kernel.home import Home, current_home

REAL_DOCKET_HOME = Path.home() / ".docket"


def _is_under(candidate: Path, parent: Path) -> bool:
    try:
        candidate.resolve().relative_to(parent.resolve())
    except (ValueError, OSError):
        return False
    return True


def _home_paths(home: Home) -> dict[str, Path]:
    """Every Path the home holds or derives: its fields and its Path-valued properties."""
    paths: dict[str, Path] = {}
    for field in dataclasses.fields(home):
        value = getattr(home, field.name)
        if isinstance(value, Path):
            paths[field.name] = value
    for name in dir(type(home)):
        if isinstance(getattr(type(home), name), property):
            value = getattr(home, name)
            if isinstance(value, Path):
                paths[name] = value
    return paths


class TestNoHomePathResolvesIntoTheRealDocketHome:
    def test_every_path_the_current_home_hands_out_is_isolated(self) -> None:
        """Asserts the autouse fixture's effect, not the module-import defaults."""
        leaked = [
            (name, str(path))
            for name, path in _home_paths(current_home()).items()
            if _is_under(path, REAL_DOCKET_HOME)
        ]
        assert not leaked, f"home paths still resolve into {REAL_DOCKET_HOME}: {leaked}"

    def test_fleet_file_is_isolated_too(self) -> None:
        """``fleet_file`` has its own override on the autouse home; pin it here so the
        override and the root cannot drift apart without a test noticing."""
        assert not _is_under(current_home().fleet_file, REAL_DOCKET_HOME), (
            f"fleet file still resolves into {REAL_DOCKET_HOME}: {current_home().fleet_file}"
        )

    def test_the_guard_covers_a_real_number_of_paths(self) -> None:
        """The guard is only as good as its list: a home whose properties stopped being
        found would pass the two tests above for nothing."""
        names = set(_home_paths(current_home()))
        assert {"root", "audit_log", "traces_dir", "approvals_dir", "fleet_file"} <= names
        assert len(names) >= 25
