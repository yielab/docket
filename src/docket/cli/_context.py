"""docket context — read-only views over an agent's memory and activity.

``run_context(agent_id, ws, sub, extra)`` returns the process exit code; the
coordinator (``cli/__init__.py``) resolves/validates the agent id and workspace
and wraps this in a Typer command, raising ``typer.Exit(code)``.

Subcommands: ``show`` (default) | ``project``. Both are pure read-only renderers
over the canonical memory layout (``core/memory.py``). Semantic search over an
agent's memory is the openclaw runtime's job (``memory_search``/``memory_get``),
not docket's — docket does not maintain a rival keyword index.
"""

from __future__ import annotations

from pathlib import Path

import docket.config as _cfg
from docket import ui
from docket.core import memory as _mem
from docket.core.utils import last_activity
from docket.edges import store


def run_context(agent_id: str, ws: Path, sub: str | None, extra: list[str]) -> int:
    """Dispatch the context subcommand. Returns the process exit code."""
    if (sub or "show") == "project":
        _context_project(agent_id, ws)
    else:
        _context_show(agent_id, ws)
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
    mem_dir = _mem.memory_dir(ws)
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
    today = _mem.today().strftime("%Y-%m-%d")
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

    mem_md = _mem.memory_md_path(ws)
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

    mem_dir = _mem.memory_dir(ws)
    mem_count = sum(1 for _ in mem_dir.glob("*.md")) if mem_dir.is_dir() else 0
    ui.console.print(f"  Memory logs: {mem_count}")
    ui.console.print(f"  Last active: {last_activity(agent_id)}")
    ui.console.print()
