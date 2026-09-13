"""The test suite must never read or write the developer's real ``~/.docket``.

``conftest.py``'s ``_isolate_docket_home`` autouse fixture is the fix; this
module is the guard that keeps it honest.

Two of the constants below -- ``PORT_ALLOC_FILE`` and ``CONVERSATIONS_FILE``
-- have no environment override at all, so an individual test cannot opt out
of the real path even deliberately. That is precisely why isolation must be
an autouse default rather than each test's own responsibility, and why this
guard asserts on the whole set rather than a sample.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.conftest import _DOCKET_HOME_PATHS

import docket.config as _cfg

REAL_DOCKET_HOME = Path.home() / ".docket"


def _is_under(candidate: Path, parent: Path) -> bool:
    try:
        candidate.resolve().relative_to(parent.resolve())
    except (ValueError, OSError):
        return False
    return True


class TestNoConfigPathResolvesIntoTheRealDocketHome:
    def test_every_docket_home_derived_path_is_isolated(self) -> None:
        """Every ``DOCKET_HOME``-derived constant points outside the real
        home -- asserts the autouse fixture's effect, not module-import
        defaults."""
        leaked = [
            (attr, str(getattr(_cfg, attr)))
            for attr, _leaf in _DOCKET_HOME_PATHS
            if _is_under(getattr(_cfg, attr), REAL_DOCKET_HOME)
        ]
        assert not leaked, f"config paths still resolve into {REAL_DOCKET_HOME}: {leaked}"

    def test_fleet_file_is_isolated_too(self) -> None:
        """``FLEET_FILE`` is covered by its own sibling fixture; pin it here so
        the two fixtures cannot drift apart without a test noticing."""
        assert not _is_under(_cfg.FLEET_FILE, REAL_DOCKET_HOME), (
            f"FLEET_FILE still resolves into {REAL_DOCKET_HOME}: {_cfg.FLEET_FILE}"
        )

    def test_the_guard_covers_every_docket_home_derived_constant(self) -> None:
        """The guard is only as good as its list: a future constant added to
        ``config.py`` as ``DOCKET_HOME / "..."`` must also be added to
        ``_DOCKET_HOME_PATHS``, or it silently escapes both the fixture and
        the two tests above. Parsed with ast, not scanned line by line, so
        a constant assignment that wraps across lines (what a formatter
        does to a long one) cannot evade it the way a text search for the
        literal ``DOCKET_HOME /`` would."""
        tree = ast.parse(Path(_cfg.__file__).read_text())
        declared = {attr for attr, _leaf in _DOCKET_HOME_PATHS} | {"FLEET_FILE"}
        found: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            # Any mention of DOCKET_HOME anywhere in the assigned value --
            # `DOCKET_HOME / "x"`, `Path(os.environ.get(..., DOCKET_HOME / "x"))`,
            # or any future nesting -- counts as deriving from it.
            if not any(
                isinstance(sub, ast.Name) and sub.id == "DOCKET_HOME"
                for sub in ast.walk(node.value)
                if node.value is not None
            ):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    found.add(target.id)
        missing = found - declared
        assert not missing, (
            f"config.py derives {sorted(missing)} from DOCKET_HOME but "
            f"conftest._DOCKET_HOME_PATHS does not isolate them"
        )
