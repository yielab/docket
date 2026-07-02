"""Shared utility functions for read-only command implementations."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import docket.config as cfg
from docket.edges import store

if TYPE_CHECKING:
    from docket.edges.adapters.system import RestartResult


def project_ids() -> list[str]:
    """Sorted list of project agent IDs (dirs containing .docket-meta.json)."""
    if not cfg.PROJECTS_DIR.is_dir():
        return []
    return sorted(
        d.name for d in cfg.PROJECTS_DIR.iterdir() if d.is_dir() and (d / cfg.META_FILE).is_file()
    )


def last_activity(agent_id: str) -> str:
    """Return the most recent memory-log date (YYYY-MM-DD) or '—'."""
    mem_dir = cfg.workspace_dir(agent_id) / "memory"
    if not mem_dir.is_dir():
        return "—"
    files = sorted(mem_dir.glob("*.md"))
    return files[-1].stem if files else "—"


_GATEWAY_UNIT = "openclaw-gateway.service"


def gateway_active() -> bool:
    """Return True if openclaw-gateway.service is active."""
    from docket.edges.adapters import system as _system

    return _system.gateway_active()


def openclaw_version() -> str:
    """Return `openclaw --version` output, or '?' if unavailable.

    The subprocess call lives behind the ACL (core has no subprocess of its
    own — ROADMAP §3); this just applies the display fallback.
    """
    from docket.edges.adapters import openclaw as _oc

    probe = _oc.openclaw_version()
    return probe.output if (probe.available and probe.returncode == 0 and probe.output) else "?"


def restart_gateway() -> RestartResult:
    """Restart openclaw-gateway.service if it is running.

    Honors DOCKET_NO_RESTART=1 for test hermeticity. Thin pass-through to the
    edges adapter; returns a typed result (never prints — cli/ renders it via
    ui.*, since core has no knowledge of terminals).
    """
    from docket.edges.adapters import system as _system

    return _system.restart_gateway()


def si_format(n: int) -> str:
    """Format a token count with SI suffix (e.g. 1_234_567 → '1.2M')."""
    f = float(n)
    for unit in ("", "K", "M", "G", "T"):
        if abs(f) < 1000.0:
            return str(int(f)) if unit == "" else f"{f:.1f}{unit}"
        f /= 1000.0
    return f"{f:.1f}P"


@dataclass
class CostTotals:
    """Aggregated token/cost totals for one agent across all sessions."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost_usd: float = 0.0
    turns: int = 0


def aggregate_cost(agent_id: str) -> CostTotals:
    """Read session JSONL files and return aggregated token/cost totals.

    Uses an incremental index (.cost-index.json) keyed by (mtime, size) so
    unchanged files are served from cache; only new/changed files are parsed.
    Set DOCKET_NO_COST_INDEX=1 to force a full recompute.
    """
    sessions_dir = cfg.OPENCLAW_DIR / "agents" / agent_id / "sessions"
    index_path = cfg.OPENCLAW_DIR / "agents" / agent_id / ".cost-index.json"
    use_index = os.environ.get("DOCKET_NO_COST_INDEX") != "1"

    index: dict[str, Any] = {}
    if use_index and index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            index = {}

    totals = CostTotals()
    seen: set[str] = set()
    changed = False

    if sessions_dir.is_dir():
        for path in sorted(sessions_dir.glob("*.jsonl")):
            name = path.name
            seen.add(name)
            try:
                st = path.stat()
                sig: list[int] = [int(st.st_mtime), st.st_size]
            except OSError:
                continue

            ent = index.get(name)
            if use_index and ent and ent.get("sig") == sig:
                t: dict[str, Any] = ent["totals"]
            else:
                t = _parse_session_file(path)
                index[name] = {"sig": sig, "totals": t}
                changed = True

            totals.input_tokens += int(t.get("input", 0))
            totals.output_tokens += int(t.get("output", 0))
            totals.cache_read += int(t.get("cacheRead", 0))
            totals.cache_write += int(t.get("cacheWrite", 0))
            totals.cost_usd += float(t.get("cost", 0.0))
            totals.turns += int(t.get("turns", 0))

    if use_index:
        for name in list(index.keys()):
            if name not in seen:
                del index[name]
                changed = True
        if changed:
            _write_cost_index(index_path, index)

    return totals


def _parse_session_file(path: Path) -> dict[str, Any]:
    t: dict[str, Any] = {
        "input": 0,
        "output": 0,
        "cacheRead": 0,
        "cacheWrite": 0,
        "cost": 0.0,
        "turns": 0,
    }
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                data: dict[str, Any] = json.loads(line)
            except Exception:
                continue
            msg = data.get("message", {})
            usage: dict[str, Any] = msg.get("usage", {}) if isinstance(msg, dict) else {}
            if usage:
                t["input"] = int(t["input"]) + int(usage.get("input", 0))
                t["output"] = int(t["output"]) + int(usage.get("output", 0))
                t["cacheRead"] = int(t["cacheRead"]) + int(usage.get("cacheRead", 0))
                t["cacheWrite"] = int(t["cacheWrite"]) + int(usage.get("cacheWrite", 0))
                cost_field = usage.get("cost", {})
                t["cost"] = float(t["cost"]) + (
                    float(cost_field.get("total", 0)) if isinstance(cost_field, dict) else 0.0
                )
                t["turns"] = int(t["turns"]) + 1
    except Exception:
        pass
    return t


def _write_cost_index(index_path: Path, index: dict[str, Any]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = index_path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(index), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, index_path)
    except Exception:
        tmp.unlink(missing_ok=True)


@dataclass
class DayRecord:
    """Cost/token totals for a single calendar day."""

    date: str
    turns: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


def cost_history(agent_id: str) -> list[DayRecord]:
    """Parse session JSONL files and return per-day records for one agent.

    Uses .cost-history.json keyed by the set of file (mtime, size) signatures.
    """
    sessions_dir = cfg.OPENCLAW_DIR / "agents" / agent_id / "sessions"
    hist_path = cfg.OPENCLAW_DIR / "agents" / agent_id / ".cost-history.json"
    use_index = os.environ.get("DOCKET_NO_COST_INDEX") != "1"

    sigs: dict[str, list[int]] = {}
    files: list[Path] = []
    if sessions_dir.is_dir():
        files = sorted(sessions_dir.glob("*.jsonl"))
        for f in files:
            try:
                st = f.stat()
                sigs[f.name] = [int(st.st_mtime), st.st_size]
            except OSError:
                pass

    cached: dict[str, Any] = {}
    if use_index and hist_path.exists():
        try:
            cached = json.loads(hist_path.read_text(encoding="utf-8"))
        except Exception:
            cached = {}

    hist: dict[str, dict[str, Any]]
    if use_index and cached.get("sigs") == sigs:
        hist = cached.get("history", {})
    else:
        hist = {}
        for f in files:
            try:
                lines = f.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    d: dict[str, Any] = json.loads(line)
                except Exception:
                    continue
                msg = d.get("message", {})
                usage: dict[str, Any] = msg.get("usage", {}) if isinstance(msg, dict) else {}
                if not usage:
                    continue
                ts = d.get("timestamp", "")
                day = ts[:10] if isinstance(ts, str) and len(ts) >= 10 else "unknown"
                b = hist.setdefault(day, {"turns": 0, "input": 0, "output": 0, "cost": 0.0})
                b["turns"] = int(b["turns"]) + 1
                b["input"] = int(b["input"]) + int(usage.get("input", 0))
                b["output"] = int(b["output"]) + int(usage.get("output", 0))
                cost_field = usage.get("cost", {})
                b["cost"] = float(b["cost"]) + (
                    float(cost_field.get("total", 0)) if isinstance(cost_field, dict) else 0.0
                )
        if use_index:
            _write_hist_index(hist_path, sigs, hist)

    return [
        DayRecord(
            date=day,
            turns=int(b["turns"]),
            input_tokens=int(b["input"]),
            output_tokens=int(b["output"]),
            cost_usd=round(float(b["cost"]), 6),
        )
        for day, b in sorted(hist.items())
    ]


def _write_hist_index(
    hist_path: Path,
    sigs: dict[str, list[int]],
    hist: dict[str, dict[str, Any]],
) -> None:
    hist_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = hist_path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps({"sigs": sigs, "history": hist}), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, hist_path)
    except Exception:
        tmp.unlink(missing_ok=True)


def model_source(agent_id: str) -> str:
    """Return 'policy' or 'pinned' for an agent's model source.

    Reads modelSource from .docket-meta.json; defaults to 'policy' if absent.
    """
    raw = store.read_json(cfg.meta_path(agent_id))
    return str(raw.get("modelSource", "policy")) or "policy"


def scan_telegram_groups() -> list[tuple[str, str, str]]:
    """Scan OpenClaw log files for Telegram group IDs.

    Returns a list of (chat_id, title, bound_agent_id) tuples.
    bound_agent_id is '' if the group has no docket binding.
    """
    import re as _re

    from docket.edges.adapters import openclaw as _oc

    log_dir = cfg.LOG_DIR
    if not log_dir.is_dir():
        return []

    chat_ids: dict[str, str] = {}  # chat_id → title
    for log_file in sorted(log_dir.glob("openclaw-*.log")):
        try:
            text = log_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _re.finditer(r'"chatId":(-[0-9]+)', text):
            gid = m.group(1)
            if gid not in chat_ids:
                title_m = _re.search(rf'"chatId":{_re.escape(gid)},"title":"([^"]*)"', text)
                chat_ids[gid] = title_m.group(1) if title_m else "unknown"

    if not chat_ids:
        return []

    oc_cfg = _oc.load_config()
    binding_map: dict[str, str] = {
        b.match.peer.id: b.agent_id for b in oc_cfg.bindings if b.match.channel == "telegram"
    }

    return [(gid, title, binding_map.get(gid, "")) for gid, title in chat_ids.items()]
