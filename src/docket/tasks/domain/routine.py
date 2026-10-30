"""A routine: a pod's standing order to enqueue a task on a schedule. This is the parsed record;
the document is validated by ``teams.config_docs``, and ``tasks.application.routines`` fires it.
See specs/functional/pod-dispatch.spec.md "Routines"."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

KEY_PREFIX = "routine:"
CHANNEL = "routine"


@dataclass(frozen=True)
class Routine:
    name: str
    schedule: str
    task_description: str
    tz: str = "UTC"
    pipeline: str | None = None
    variables: dict[str, str] = field(default_factory=dict)
    priority: str = "normal"
    catch_up: str = "skip"
    overlap: str = "skip"
    enabled: bool = True
    scope: str = ""
    path: str = ""

    @classmethod
    def from_document(cls, doc: Mapping[str, Any], *, scope: str = "", path: str = "") -> Routine:
        """The record of a document ``load_document`` already validated."""
        task = doc["task"]
        return cls(
            name=str(doc["name"]),
            schedule=str(doc["schedule"]),
            task_description=str(task["description"]),
            tz=str(doc.get("tz", "UTC")),
            pipeline=task.get("pipeline"),
            variables=dict(task.get("variables") or {}),
            priority=str(task.get("priority", "normal")),
            catch_up=str(doc.get("catchUp", "skip")),
            overlap=str(doc.get("overlap", "skip")),
            enabled=bool(doc.get("enabled", True)),
            scope=scope,
            path=path,
        )

    @property
    def key_prefix(self) -> str:
        return f"{KEY_PREFIX}{self.name}:"

    def key_for(self, slot: datetime) -> str:
        """The idempotency key of the task fired for *slot*."""
        return f"{self.key_prefix}{stamp(slot)}"


def stamp(moment: datetime) -> str:
    """*moment* in UTC as ``2026-11-03T08:00:00Z``: the form a slot has in a key and in the state."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
