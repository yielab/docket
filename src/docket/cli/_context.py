"""docket context — agent context and memory management.

``run_context(agent_id, ws, sub, extra)`` returns the process exit code; the
coordinator (``cli/__init__.py``) resolves/validates the agent id and
workspace (it already owns ``_pick_agent`` for the interactive picker used by
several commands) and then wraps this in a Typer command, raising
``typer.Exit(code)``.

Subcommands: show (default) | search <query> | index | snapshot | compress |
project. An unrecognized subcommand is treated as the start of a free-text
search query (``docket context <id> some words`` == ``... search some words``).
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import gzip as _gzip
import json as _json
import re as _re
import shutil as _shutil
from pathlib import Path

import docket.config as _cfg
from docket import ui
from docket.core.utils import last_activity
from docket.edges import store

_CONTEXT_SUBS = {"show", "search", "index", "snapshot", "compress", "project"}


def run_context(agent_id: str, ws: Path, sub: str | None, extra: list[str]) -> int:
    """Dispatch the context subcommand. Returns the process exit code."""
    action = sub or "show"

    if action not in _CONTEXT_SUBS:
        query_parts = [action, *extra]
        return _context_search(agent_id, ws, query_parts)

    if action == "show":
        _context_show(agent_id, ws)
        return 0
    if action == "search":
        return _context_search(agent_id, ws, extra)
    if action == "index":
        _context_index(agent_id, ws)
        return 0
    if action == "snapshot":
        _context_snapshot(agent_id, ws)
        return 0
    if action == "compress":
        _context_compress(agent_id, ws)
        return 0
    if action == "project":
        _context_project(agent_id, ws)
        return 0
    return 0


def _context_show(agent_id: str, ws: Path) -> None:
    try:
        raw = store.read_json(_cfg.meta_path(agent_id))
        name = str(raw.get("name", agent_id))
    except Exception:
        name = agent_id

    ui.header(f"Context: {name}")
    ui.console.print()

    ui.console.print("[bold]Recent Activity[/bold]")
    mem_dir = ws / "memory"
    if mem_dir.is_dir():
        mem_files = sorted(mem_dir.glob("*.md"), reverse=True)[:3]
        if mem_files:
            for mf in mem_files:
                ui.console.print(f"  [dim]{mf.name}[/dim]")
                try:
                    lines = mf.read_text(encoding="utf-8").splitlines()[-5:]
                    for ln in lines:
                        ui.console.print(f"    {ln}")
                except OSError:
                    pass
        else:
            ui.console.print("  [dim]No memory logs yet.[/dim]")
    else:
        ui.console.print("  [dim]No memory directory.[/dim]")

    ui.console.print()

    ui.console.print("[bold]Active Tasks[/bold]")
    hb = ws / "HEARTBEAT.md"
    if hb.is_file():
        task_lines = [
            ln for ln in hb.read_text(encoding="utf-8").splitlines() if ln.startswith("- [")
        ][:5]
        if task_lines:
            for tl in task_lines:
                ui.console.print(f"  {tl}")
        else:
            ui.console.print("  [dim]No active tasks.[/dim]")
    else:
        ui.console.print("  [dim]HEARTBEAT.md not found.[/dim]")

    ui.console.print()

    ui.console.print("[bold]Gateway Activity[/bold]")
    today = _dt.date.today().strftime("%Y-%m-%d")
    log_file = _cfg.LOG_DIR / f"openclaw-{today}.log"
    if log_file.is_file():
        try:
            all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            matched = [ln for ln in all_lines if agent_id in ln][-5:]
            if matched:
                for ln in matched:
                    ui.console.print(f"  [dim]{ln}[/dim]")
            else:
                ui.console.print(f"  [dim]No entries today for '{agent_id}'.[/dim]")
        except OSError:
            ui.console.print("  [dim]Cannot read log file.[/dim]")
    else:
        ui.console.print(f"  [dim]No log for {today}.[/dim]")

    ui.console.print()

    ui.console.print("[bold]Context Statistics[/bold]")
    mem_count = sum(1 for _ in mem_dir.glob("*.md")) if mem_dir.is_dir() else 0
    activity = last_activity(agent_id)

    sessions_dir = _cfg.OPENCLAW_DIR / "agents" / agent_id / "sessions"
    session_size = "n/a"
    if sessions_dir.is_dir():
        session_files = sorted(sessions_dir.glob("*.jsonl"))
        if session_files:
            try:
                size_bytes = session_files[-1].stat().st_size
                session_size = f"{size_bytes // 1024}KB"
            except OSError:
                pass

    ui.console.print(f"  Log files:    {mem_count}")
    ui.console.print(f"  Session size: {session_size}")
    ui.console.print(f"  Last active:  {activity}")

    ui.console.print()
    ui.console.print("[bold]Quick Actions[/bold]")
    ui.console.print(f"  docket context {agent_id} search <query>  — search memory")
    ui.console.print(f"  docket context {agent_id} index            — build search index")
    ui.console.print(f"  docket context {agent_id} snapshot         — export SNAPSHOT.md")
    ui.console.print(f"  docket context {agent_id} compress         — gzip old logs")
    ui.console.print()


def _context_search(agent_id: str, ws: Path, query_parts: list[str]) -> int:
    query = " ".join(query_parts).strip()
    if not query:
        ui.error("Usage: docket context <id> search <query>")
        return 1

    index_path = ws / ".memory-index.json"
    if not index_path.is_file():
        ui.warn("Memory not indexed yet. Run: docket context <id> index")
        return 0

    try:
        index = _json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        ui.error("Failed to read memory index.")
        return 1

    keywords = index.get("keywords", {})
    decisions = index.get("decisions", [])
    files = index.get("files", [])

    query_lower = query.lower()
    matches: list[str] = []

    for kw, occurrences in keywords.items():
        if query_lower in kw.lower():
            for occ in occurrences:
                matches.append(f"[keyword] {kw} in {occ}")

    for dec in decisions:
        if query_lower in dec.lower():
            matches.append(f"[decision] {dec}")

    for fname in files:
        if query_lower in fname.lower():
            matches.append(f"[file] {fname}")

    ui.header(f"Search: {query}")
    ui.console.print()
    if matches:
        for m in matches[:20]:
            ui.console.print(f"  {m}")
        if len(matches) > 20:
            ui.console.print(f"  [dim]... {len(matches) - 20} more matches[/dim]")
    else:
        ui.console.print(f"  [dim]No matches for '{query}'.[/dim]")
    ui.console.print()
    return 0


def _context_index(agent_id: str, ws: Path) -> None:
    mem_dir = ws / "memory"
    files: list[str] = []
    keywords: dict[str, list[str]] = {}
    decisions: list[str] = []

    if mem_dir.is_dir():
        for mf in sorted(mem_dir.glob("*.md")):
            files.append(mf.name)
            try:
                content = mf.read_text(encoding="utf-8")
            except OSError:
                continue
            for word in _re.findall(r"\*\*([^*]+)\*\*|`([^`]+)`", content):
                kw = (word[0] or word[1]).strip()
                if kw:
                    kw_lower = kw.lower()
                    keywords.setdefault(kw_lower, [])
                    if mf.name not in keywords[kw_lower]:
                        keywords[kw_lower].append(mf.name)

    memory_md = ws / "MEMORY.md"
    if memory_md.is_file():
        try:
            for ln in memory_md.read_text(encoding="utf-8").splitlines():
                if ln.startswith("## "):
                    decisions.append(ln[3:].strip())
        except OSError:
            pass

    index = {
        "indexed_at": _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": files,
        "keywords": keywords,
        "decisions": decisions,
    }

    index_path = ws / ".memory-index.json"
    store.write_json(index_path, index)

    ui.success(
        f"Index built: {len(files)} file(s), {len(keywords)} keyword(s), {len(decisions)} decision(s)"
    )


def _context_snapshot(agent_id: str, ws: Path) -> None:
    raw = store.read_json(_cfg.meta_path(agent_id))
    name = str(raw.get("name", agent_id))
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines: list[str] = [
        f"# SNAPSHOT.md — {name}",
        "",
        f"Generated: {now}",
        "",
        "## Metadata",
        f"- Agent ID: {agent_id}",
        f"- Type: {raw.get('type', 'repo')}",
        f"- Model: {raw.get('model', _cfg.DEFAULT_MODEL)}",
        f"- Session Key: {raw.get('sessionKey', '')}",
        f"- Codebase: {raw.get('codebase', '')}",
        "",
    ]

    lines.append("## Recent Activity")
    mem_dir = ws / "memory"
    if mem_dir.is_dir():
        for mf in sorted(mem_dir.glob("*.md"), reverse=True)[:3]:
            lines.append("")
            lines.append(f"### {mf.name}")
            try:
                for ln in mf.read_text(encoding="utf-8").splitlines()[-10:]:
                    lines.append(ln)
            except OSError:
                pass
    lines.append("")

    hb = ws / "HEARTBEAT.md"
    if hb.is_file():
        lines.append("## HEARTBEAT")
        with contextlib.suppress(OSError):
            lines.extend(hb.read_text(encoding="utf-8").splitlines())
        lines.append("")

    mem_md = ws / "MEMORY.md"
    if mem_md.is_file():
        lines.append("## MEMORY")
        with contextlib.suppress(OSError):
            lines.extend(mem_md.read_text(encoding="utf-8").splitlines())
        lines.append("")

    mem_count = sum(1 for _ in mem_dir.glob("*.md")) if mem_dir.is_dir() else 0
    lines.append("## Stats")
    lines.append(f"- Memory log files: {mem_count}")
    lines.append(f"- Last active: {last_activity(agent_id)}")

    snap_path = ws / "SNAPSHOT.md"
    snap_path.write_text("\n".join(lines), encoding="utf-8")
    snap_path.chmod(0o600)
    ui.success(f"Snapshot written: {snap_path}")


def _context_compress(agent_id: str, ws: Path) -> None:
    mem_dir = ws / "memory"
    if not mem_dir.is_dir():
        ui.info("No memory directory.")
        return

    cutoff = _dt.datetime.now() - _dt.timedelta(days=30)
    old_files: list[Path] = []
    for f in mem_dir.glob("*.md"):
        try:
            mtime = _dt.datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                old_files.append(f)
        except OSError:
            pass

    if not old_files:
        ui.info("No old logs to compress (all memory logs are < 30 days old).")
        return

    archive_dir = mem_dir / "archive"
    archive_dir.mkdir(exist_ok=True)
    archive_dir.chmod(0o700)

    for f in old_files:
        dest = archive_dir / (f.name + ".gz")
        with f.open("rb") as f_in, _gzip.open(dest, "wb") as f_out:
            _shutil.copyfileobj(f_in, f_out)
        f.unlink()

    ui.success(f"Compressed {len(old_files)} old log(s) → memory/archive/")


def _context_project(agent_id: str, ws: Path) -> None:
    raw = store.read_json(_cfg.meta_path(agent_id))
    name = str(raw.get("name", agent_id))

    ui.header(f"Project Context: {name}")
    ui.console.print()
    ui.console.print(f"  [bold]{'Codebase:':<16}[/bold] {raw.get('codebase', '—')}")
    ui.console.print(f"  [bold]{'Stack:':<16}[/bold] {raw.get('stack', '—')}")
    ui.console.print(f"  [bold]{'Model:':<16}[/bold] {raw.get('model', '—')}")
    ui.console.print(f"  [bold]{'Session Key:':<16}[/bold] {raw.get('sessionKey', '—')}")
    ui.console.print()

    hb = ws / "HEARTBEAT.md"
    if hb.is_file():
        task_lines = [
            ln for ln in hb.read_text(encoding="utf-8").splitlines() if ln.startswith("- [")
        ]
        ui.console.print("[bold]Active Tasks[/bold]")
        if task_lines:
            for tl in task_lines[:5]:
                ui.console.print(f"  {tl}")
        else:
            ui.console.print("  [dim]No active tasks.[/dim]")
        ui.console.print()

    mem_md = ws / "MEMORY.md"
    if mem_md.is_file():
        headers = [
            ln[3:].strip()
            for ln in mem_md.read_text(encoding="utf-8").splitlines()
            if ln.startswith("## ")
        ]
        ui.console.print("[bold]Memory Sections[/bold]")
        for h in headers:
            ui.console.print(f"  ## {h}")
        ui.console.print()

    mem_dir = ws / "memory"
    mem_count = sum(1 for _ in mem_dir.glob("*.md")) if mem_dir.is_dir() else 0
    ui.console.print(f"  Memory logs: {mem_count}")
    ui.console.print(f"  Last active: {last_activity(agent_id)}")
    ui.console.print()
