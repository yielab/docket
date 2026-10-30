"""The send quota: a pod may send so many times in a trailing window (ADR 0036 decision 7).

The one stateful rule. A policy document carries ``limit: {kind: send | tool: <name>, count: <n>,
per: hour | day}``; this module validates and parses the clause, counts the executions a pod has
made and appends a new one. The counter is a JSON file under the home's state directory written
only through ``platform/store.py``; it holds one ``[epoch, tool]`` pair per execution of the last
day, so a window is a count over the entries younger than it. ``governance.gate`` asks
``used`` before a ``send`` call and calls ``record_executed`` after one ran
(``specs/functional/security-gates.spec.md``, in-turn tool-call gate 18)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from docket.kernel import clock as _clock
from docket.kernel.home import current_home
from docket.platform import read_json, read_modify_write

_PER_SECONDS: dict[str, int] = {"hour": 3600, "day": 86400}
_PER_LABEL: dict[str, str] = {"hour": "this hour", "day": "today"}
_KEYS = frozenset({"kind", "tool", "count", "per"})
_KEEP_S = max(_PER_SECONDS.values())


@dataclass(frozen=True)
class Limit:
    """One quota: ``count`` executions per ``per`` of the ``send`` kind, or of one ``tool``."""

    policy_id: str
    count: int
    per: str
    tool: str = ""

    @property
    def scope(self) -> str:
        return self.tool or "send"

    def covers(self, tool_name: str, tool_kind: str) -> bool:
        return tool_kind == "send" and (not self.tool or self.tool == tool_name)


def validate_limit(p: dict[str, Any], label: str) -> str:
    """'' when the canonical policy *p* is a valid quota, else the error naming the field."""
    limit = p["limit"]
    if not isinstance(limit, dict):
        return f"{label}: limit must be a mapping"
    if p.get("match") is not None or p.get("when") is not None:
        return f"{label}: limit cannot be combined with when or match"
    if p.get("hook") != "pre_tool_call":
        return f"{label}: a limit applies to a tool call, so on must be toolCall"
    if p.get("action") != "block":
        return f"{label}: a limit blocks, so then must be block"
    unknown = sorted(str(k) for k in set(limit) - _KEYS)
    if unknown:
        return f"{label}: unknown limit key(s) {unknown} (valid: kind, tool, count, per)"
    tool, kind = limit.get("tool"), limit.get("kind")
    if (tool is None) == (kind is None):
        return f"{label}: limit needs exactly one of kind (send) or tool"
    if kind is not None and kind != "send":
        return f"{label}: limit.kind must be send, got {kind!r}"
    if tool is not None and not (isinstance(tool, str) and tool.strip()):
        return f"{label}: limit.tool must be a non-empty tool name"
    count = limit.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        return f"{label}: limit.count must be an integer of at least 1"
    if limit.get("per") not in _PER_SECONDS:
        return f"{label}: limit.per must be hour or day"
    return ""


def parse_limit(p: dict[str, Any]) -> Limit:
    """The :class:`Limit` of a canonical policy that passed :func:`validate_limit`."""
    limit = p["limit"]
    return Limit(str(p["id"]), int(limit["count"]), str(limit["per"]), str(limit.get("tool") or ""))


def _entries(pod: str) -> list[list[Any]]:
    try:
        raw = read_json(current_home().quota_file).get("pods", {}).get(pod, [])
    except (ValueError, OSError):
        return []  # an unreadable counter counts as empty (the store has quarantined it)
    return [e for e in raw if isinstance(e, list) and len(e) == 2] if isinstance(raw, list) else []


def used(pod: str, limit: Limit) -> int:
    """The executions *pod* made inside *limit*'s trailing window that *limit* covers."""
    since = _clock.epoch() - _PER_SECONDS[limit.per]
    return sum(
        1
        for at, tool in _entries(pod)
        if isinstance(at, int | float) and at > since and (not limit.tool or tool == limit.tool)
    )


def refusal(limit: Limit, spent: int) -> str:
    """What a call over *limit* is told: the count and the window."""
    return f"send quota reached: {spent}/{limit.count} per {limit.per} (policy {limit.policy_id!r})"


def record_executed(pod: str, tool: str) -> None:
    """Append one execution of *tool* by *pod*, dropping what is older than any window."""
    now = _clock.epoch()

    def _append(doc: dict[str, Any]) -> dict[str, Any]:
        pods = doc.setdefault("pods", {})
        kept = [
            e
            for e in pods.get(pod, [])
            if isinstance(e, list)
            and len(e) == 2
            and isinstance(e[0], int | float)
            and e[0] > now - _KEEP_S
        ]
        pods[pod] = [*kept, [now, tool]]
        return doc

    read_modify_write(current_home().quota_file, _append)


def quota_rows(pod: str, limits: list[Limit]) -> list[dict[str, Any]]:
    """One row per quota for ``docket status``: ``scope``, ``used``, ``count`` and ``per``."""
    return [
        {"scope": lim.scope, "used": used(pod, lim), "count": lim.count, "per": lim.per}
        for lim in limits
    ]


def row_text(row: dict[str, Any]) -> str:
    """A row as ``send 2/2 today``."""
    return f"{row['scope']} {row['used']}/{row['count']} {_PER_LABEL[row['per']]}"
