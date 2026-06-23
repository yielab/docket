"""Role success-rate drift detection (port of lib/helpers/drift.sh, D1-D3).

Compares each agent role's rolling METRICS_WINDOW success rate against the
trailing BASELINE_WINDOW baseline. When current < baseline - DRIFT_THRESHOLD a
drift_alert trace event is emitted (rate-limited to one alert per role per
DRIFT_COOLDOWN seconds). Aborted sessions count as failures (D-6).

Only the ``drift_check_all`` entry point that ``docket serve`` calls is ported
here; the Bash also notified via Telegram, which has no Python equivalent yet —
that side-effect was best-effort (``|| true``) and is omitted.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any

import docket.config as _cfg

_DRIFT_STATE_FILE: Path = _cfg.DOCKET_HOME / "drift-state.json"


def _terminal_statuses(role: str, project_filter: str, max_n: int) -> list[str]:
    """Collect up to *max_n* terminal-session statuses for *role*.

    Mirrors collect_terminal_sessions(): walks trace files in sorted order, and
    for each file records the status of the first session_end seen while *role*
    is the active agent_role (status defaults to "success" when absent).
    """
    traces_dir = _cfg.TRACES_DIR
    if not traces_dir.is_dir():
        return []
    out: list[str] = []
    for tf in sorted(traces_dir.glob("**/*.jsonl")):
        try:
            rel = tf.relative_to(traces_dir).parts
        except ValueError:
            rel = (tf.name,)
        project = rel[0] if len(rel) > 1 else "unknown"
        if project_filter and project != project_filter:
            continue
        cur_role: str | None = None
        status: str | None = None
        try:
            text = tf.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("agent_role") == role:
                cur_role = role
            if rec.get("event_type") == "session_end" and cur_role == role:
                payload = rec.get("payload")
                if isinstance(payload, dict):
                    status = str(payload.get("status", "success"))
                else:
                    status = "success"
                break
        if cur_role == role and status:
            out.append(status)
        if len(out) >= max_n:
            break
    return out


def _success_rate(statuses: list[str]) -> float | None:
    if not statuses:
        return None
    return sum(1 for s in statuses if s == "success") / len(statuses) * 100


def drift_check_role(role: str, project_filter: str = "") -> tuple[float, float] | None:
    """Return (baseline_rate, current_rate) when *role* has drifted, else None.

    Returns None when there is too little data, no drift, or the per-role
    cooldown is active. On a real drift it records the alert timestamp into the
    drift-state file (atomic, 0600) before returning — matching drift.sh.
    """
    window = _cfg.METRICS_WINDOW
    baseline_win = _cfg.BASELINE_WINDOW
    threshold = _cfg.DRIFT_THRESHOLD
    cooldown = _cfg.DRIFT_COOLDOWN

    statuses = _terminal_statuses(role, project_filter, baseline_win + window)
    if len(statuses) < window:
        return None

    baseline = statuses[:-window]
    current = statuses[-window:]
    base_rate = _success_rate(baseline)
    curr_rate = _success_rate(current)
    if base_rate is None or curr_rate is None:
        return None
    if curr_rate >= base_rate - threshold:
        return None

    try:
        state: dict[str, Any] = json.loads(_DRIFT_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        state = {}

    now = _dt.datetime.now(_dt.UTC).timestamp()
    last_alert = 0.0
    last_map = state.get("last_alert")
    if isinstance(last_map, dict):
        try:
            last_alert = float(last_map.get(role, 0))
        except (TypeError, ValueError):
            last_alert = 0.0
    if (now - last_alert) < cooldown:
        return None

    if not isinstance(state.get("last_alert"), dict):
        state["last_alert"] = {}
    state["last_alert"][role] = now
    tmp = _DRIFT_STATE_FILE.with_suffix(_DRIFT_STATE_FILE.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, _DRIFT_STATE_FILE)

    return (round(base_rate, 1), round(curr_rate, 1))


def _roles_in_traces() -> list[str]:
    """Sorted, deduped agent_roles present in the trace store (excluding 'unknown')."""
    traces_dir = _cfg.TRACES_DIR
    if not traces_dir.is_dir():
        return []
    roles: set[str] = set()
    for tf in traces_dir.glob("**/*.jsonl"):
        try:
            text = tf.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = str(rec.get("agent_role", ""))
            if role and role != "unknown":
                roles.add(role)
    return sorted(roles)


def drift_check_all() -> None:
    """Check every role represented in the trace store (port of drift_check_all).

    For each drifted role, emits a drift_alert trace event. Best-effort: any
    failure (including the trace write) is swallowed so the serve loop never
    crashes. The Bash also logged a warning and notified Telegram; the warning
    has no stdout home in the serve loop and Telegram has no Python port yet.
    """
    for role in _roles_in_traces():
        try:
            result = drift_check_role(role)
        except Exception:
            continue
        if result is None:
            continue
        base_rate, curr_rate = result
        try:
            from docket.core import trace as _trace

            _trace.trace_event(
                role,
                f"drift-{os.getpid()}",
                role,
                "drift_alert",
                json.dumps(
                    {
                        "role": role,
                        "baseline_rate": base_rate,
                        "current_rate": curr_rate,
                        "threshold": _cfg.DRIFT_THRESHOLD,
                    }
                ),
            )
        except Exception:
            continue
