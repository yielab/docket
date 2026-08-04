"""The test suite must never read or write the developer's real ``~/.docket``.

Phase 19 P19-6 decoupled ``DOCKET_HOME`` from ``OPENCLAW_DIR``. Before that
card the two were the same physical directory, so every test that repointed
``OPENCLAW_DIR`` for hermeticity isolated docket's own state -- traces,
approvals, sessions, conversations, port allocations -- **for free**.
Decoupling them silently removed that safety net from every such test.

This was not theoretical. Measured on the wave-10 integration merge: a full
``uv run pytest`` created real approval records, trace JSONL files,
``docket-conversations.json`` and ``port-allocations.json`` under the
developer's actual ``~/.docket``, found by snapshotting the directory either
side of a run. ``conftest.py``'s ``_isolate_docket_home`` autouse fixture is
the fix; this module is the guard that keeps it honest.

Two of the constants below -- ``PORT_ALLOC_FILE`` and ``CONVERSATIONS_FILE``
-- have no environment override at all, so an individual test cannot opt out
of the real path even deliberately. That is precisely why isolation has to be
an autouse default rather than each test's own responsibility, and why this
guard asserts on the whole set rather than a sample.
"""

from __future__ import annotations

import ast
from pathlib import Path

import docket.config as _cfg

from .conftest import _DOCKET_HOME_PATHS

REAL_DOCKET_HOME = Path.home() / ".docket"


def _is_under(candidate: Path, parent: Path) -> bool:
    try:
        candidate.resolve().relative_to(parent.resolve())
    except (ValueError, OSError):
        return False
    return True


class TestNoConfigPathResolvesIntoTheRealDocketHome:
    def test_every_docket_home_derived_path_is_isolated(self) -> None:
        """Every ``DOCKET_HOME``-derived constant points outside the real home.

        The autouse fixture is active here (it is active for every test), so
        this asserts the fixture's effect, not the module-import defaults.
        """
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
        """The guard is only as good as its list.

        A future constant added to ``config.py`` as ``DOCKET_HOME / "..."``
        must also be added to ``_DOCKET_HOME_PATHS``, or it silently escapes
        both the fixture and the two tests above. This parses ``config.py``
        and fails on any such constant the list does not name -- the same
        "ask what set the guard actually checks" discipline that caught two
        guards verifying the wrong set in Phase 16 wave 7.

        **Parsed with ast, not scanned line by line.** The original version of
        this test split ``config.py`` into lines and looked for the literal
        ``DOCKET_HOME /``, which meant a constant whose assignment wrapped
        across lines -- exactly what a formatter does to a long one -- evaded
        it completely. P19-8 hit that for real: its first draft of
        ``TELEGRAM_OFFSET_FILE`` wrapped, the guard stayed green, and the
        constant would have written to the developer's real ``~/.docket``.
        The card reformatted its constant to one line to get the guard to
        fire, which fixed that instance and left the hole. An ast walk sees
        the assignment regardless of how it is formatted.
        """
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
