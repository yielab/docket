"""The port a pod's records sit behind, and the values it exchanges
(specs/functional/pod-records.spec.md "Module API").

A `RecordStore` speaks the domain: sets, rows, origins and bounds. It names no engine, so a second
backend is one adapter module, one line in the factory `bootstrap` binds (`kernel.ports.records`)
and one entry in the conformance suite. The rules every backend shares are in `records_rules`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from docket.kernel.records import RecordSet

Row = dict[str, Any]


@dataclass(frozen=True)
class RecordOrigin:
    """The hop a write came from; docket fills it, the model never does."""

    task: str | None = None
    session: str | None = None
    step: str | None = None


@dataclass(frozen=True)
class SetChange:
    """What declaring a set does: creates it, or adds these columns to it."""

    created: bool
    added: tuple[str, ...]


@dataclass(frozen=True)
class AddOutcome:
    """The row an add returns, and whether this call wrote it."""

    row: Row
    created: bool


@dataclass(frozen=True)
class Rows:
    """The columns of a read, the rows kept and the number left out."""

    columns: tuple[str, ...]
    rows: list[tuple[Any, ...]]
    cut: int


@dataclass(frozen=True)
class ReadLimits:
    """The bounds of a read: rows and characters kept (None for no bound), seconds allowed.
    `export` honours only `timeout_s`."""

    max_rows: int | None = None
    max_chars: int | None = None
    timeout_s: float = 5.0


class RecordStore(Protocol):
    """One pod's records; a refusal is a `RecordsError` and changes nothing. `read` and `export` take
    a read-only statement in the backend's own SQL dialect (SQLite's for the SQLite adapter);
    docket does not translate it."""

    def declare(self, record_set: RecordSet) -> SetChange:
        """Create the set or add its new columns; refuse a removal, rename, retype or new key."""
        ...

    def plan(self, record_set: RecordSet) -> SetChange:
        """What `declare` would do, changing nothing; refuses what `declare` would refuse."""
        ...

    def has(self, set_name: str) -> bool:
        """Whether the set is declared; false before the pod has written anything."""
        ...

    def add(self, set_name: str, values: Row, origin: RecordOrigin) -> AddOutcome:
        """Insert a row, or return the row that holds the same key with `created` false."""
        ...

    def update(self, set_name: str, match: Row, values: Row, origin: RecordOrigin) -> Row:
        """Change declared columns of the one row `match` names by `_id` or by the key."""
        ...

    def read(self, statement: str, limits: ReadLimits) -> Rows:
        """Run one read-only statement; keep what `limits` allow and count the rest as cut."""
        ...

    def export(self, statement: str, target: Path, fmt: str, limits: ReadLimits) -> int:
        """Write every row of one read-only statement to *target* as csv or markdown; the count."""
        ...
