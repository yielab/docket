"""Memory domain — the single owner of an agent's on-disk memory layout.

Every fact about *where* memory lives, *what* it is named, *which clock* names
it, and *what contract the openclaw runtime imposes on it* lives here. The CLI
surfaces (``cli/_context.py``, the ``docket maintain`` checks in ``cli/_agents.py``,
``cli/_doctor.py``) and the provisioning flow (``core/provisioning.py``) are thin
callers over this module — none of them re-derive paths or dates.

## The artifacts

- ``MEMORY.md``            — long-term curated project facts (repo, stack,
                             architecture, status). Written by the agent; seeded
                             with a stub so the runtime's memory backend has a
                             root document from turn one.
- ``memory/YYYY-MM-DD.md`` — daily logs, one file per day.
- ``WORKFLOW_AUTO.md``     — the startup protocol. See "The runtime contract".
- ``HEARTBEAT.md``         — the durable in-flight task ledger (body from
                             ``heartbeat_seed`` here; rendered by _pod.py /
                             _agents.py). Written before starting multi-step work
                             and resumed on reset, per the WORKFLOW_AUTO contract.

## The runtime contract

The openclaw gateway runs a *post-compaction audit* after every context reset
(``dist/*.js``: ``DEFAULT_REQUIRED_READS = ["WORKFLOW_AUTO.md", /memory\\/\\d{4}-\\d{2}-\\d{2}\\.md/]``).
It checks the agent issued a Read for those files and, if not, injects a warning
demanding it. docket is the provisioner, so docket must make them *exist* — else
the audit can never pass and a weak model loops offering to create them. Because
``WORKFLOW_AUTO.md`` is the one file the runtime forces the agent to re-read on
every reset, it is also where we anchor the codebase path and the read order so
they survive compaction even when ``SOUL.md``/``MEMORY.md`` fall out of context.

One clock: all day math is **UTC**, matching ``.docket-meta.json`` ``created``
and the trace/audit timestamps, so docket never disagrees with itself about
which daily file is "today" across a local-midnight boundary.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
from pathlib import Path

# --- openclaw runtime contract (keep in sync with DEFAULT_REQUIRED_READS) -----

#: The always-re-read startup file the runtime audits for.
REQUIRED_STARTUP_FILE = "WORKFLOW_AUTO.md"

#: strftime pattern for the daily memory file the runtime audits for.
#: Runtime regex: ``memory/\d{4}-\d{2}-\d{2}.md``.
DAILY_MEMORY_PATTERN = "memory/%Y-%m-%d.md"

#: Long-term curated memory document (runtime memory-backend root).
MEMORY_FILE = "MEMORY.md"

#: Durable task ledger (in-flight work that must survive a context reset).
HEARTBEAT_FILE = "HEARTBEAT.md"

#: Bumped when the generated WORKFLOW_AUTO.md body changes. Embedded as a marker
#: so ``docket doctor`` can detect and re-seed *stale* content, not just absence.
#: v3 adds the resume/durability contract (write in-flight tasks to HEARTBEAT.md
#: before starting; resume unchecked tasks on reset instead of greeting idle).
CONTRACT_VERSION = 3
_CONTRACT_MARKER = f"<!-- docket-contract: v{CONTRACT_VERSION} -->"


# --- date + path canon (UTC everywhere) ---------------------------------------


def today() -> _dt.date:
    """Today's date in UTC — the one clock for all memory/day math."""
    return _dt.datetime.now(_dt.UTC).date()


def today_memory_relpath(day: _dt.date | None = None) -> str:
    """Workspace-relative path of the daily memory file the runtime expects."""
    return (day or today()).strftime(DAILY_MEMORY_PATTERN)


def memory_dir(ws: Path) -> Path:
    return ws / "memory"


def daily_log_path(ws: Path, day: _dt.date | None = None) -> Path:
    return ws / today_memory_relpath(day)


def memory_md_path(ws: Path) -> Path:
    return ws / MEMORY_FILE


def last_activity(ws: Path) -> str:
    """Most recent daily-log date (``YYYY-MM-DD``) for *ws*, or ``—``."""
    mem = memory_dir(ws)
    if not mem.is_dir():
        return "—"
    logs = sorted(mem.glob("*.md"))
    return logs[-1].stem if logs else "—"


# --- contract file bodies -----------------------------------------------------


def _workflow_auto_text(
    *, project: str, codebase: str, stack: str, origin: str, work_dir: str = ""
) -> str:
    # ROADMAP Phase 16 W-7: a `workdir`-kind pod blueprint (research/content/ops)
    # has no codebase at all — routing to a dedicated sibling function (rather
    # than branching mid-string here) keeps the pre-W-7 codebase-flavored text
    # below byte-for-byte untouched for every existing caller (work_dir="").
    if work_dir.strip():
        return _workflow_auto_text_workdir(
            project=project, work_dir=work_dir, stack=stack, origin=origin
        )
    cb = codebase.strip() or "(none configured yet — ask the human for the repo path)"
    origin_line = f"- origin: `{origin}`\n" if origin.strip() else ""
    stack_line = f"- stack: {stack}\n" if stack.strip() else ""
    # Self-contained: re-read on every reset, so everything a just-reset agent
    # needs to reorient lives here, in reading order, codebase first. The daily
    # log is described as a *pattern*, never a frozen filename (which would go
    # stale the next day and point a weak model at a file that doesn't exist).
    return (
        f"{_CONTRACT_MARKER}\n"
        f"# WORKFLOW_AUTO.md — {project} startup protocol\n\n"
        "_The runtime makes you re-read this file after every context reset. "
        "Read it top to bottom before doing anything else._\n\n"
        "## Your codebase\n"
        f"`{cb}`\n\n"
        "All real work happens **here**, not in this agent workspace. Before any "
        "file operation, `cd` into the codebase (or use absolute paths under it). "
        "Treat relative paths as relative to the codebase root.\n\n"
        "## Resume before you greet\n"
        "A context reset wiped your working memory — not your job. **Before** you "
        f"reply, greet, or say there is nothing to do, open `{HEARTBEAT_FILE}`:\n"
        "- If `## Active Tasks` has any unchecked `- [ ]` step, you were interrupted "
        "**mid-task**. Pick up the next unchecked step and keep going — do not "
        "restart from scratch and do not announce you are idle.\n"
        "- Only when every task is checked off or removed are you actually idle.\n\n"
        "## Durability rule — how a task survives a reset\n"
        "The moment you accept work you can't finish in one reply (anything "
        f"multi-step, multi-file, or long-running), **write it to `{HEARTBEAT_FILE}` "
        "under `## Active Tasks` as a checklist _before you start_**, then tick "
        "steps off as you go. In-context plans and mental notes do **not** survive "
        "a context reset — only what is on disk does. An unwritten task is a task "
        "you will silently lose.\n\n"
        "## Read these, in order\n"
        f"1. `{HEARTBEAT_FILE}` — active tasks / pending decisions (always; obey the "
        "resume rule above before doing anything else).\n"
        "2. `SOUL.md` — who you are, your scope, and your safety rules.\n"
        "3. `MEMORY.md` — what this project **is** and durable facts about it "
        "(product summary, architecture, current state).\n"
        "4. `memory/YYYY-MM-DD.md` — today's log (create it if missing, one file "
        "per day); read yesterday's only if the task needs prior context. Don't "
        "slurp the whole `memory/` dir.\n\n"
        '## Answering "what is this project about"\n'
        "Answer from **MEMORY.md → What this project is**: describe what the "
        "product does and who it's for. Do **not** answer with your pod role, "
        "agent id, session key, or workspace paths — that is *your* scaffolding, "
        "not the project. If that section is still a placeholder, read the "
        "codebase `README` (and `docs/`) first and fill it in before answering.\n\n"
        "## Repo\n"
        f"{origin_line}"
        f"- codebase: `{cb}`\n"
        f"{stack_line}\n"
        "## If a file 'isn't found'\n"
        "You are almost certainly in the wrong directory — the agent workspace, "
        "not the codebase. Re-check that you are under the codebase root above "
        "**before** concluding the file does not exist or offering to create it.\n"
    )


def _workflow_auto_text_workdir(*, project: str, work_dir: str, stack: str, origin: str) -> str:
    """The `workdir`-flavored WORKFLOW_AUTO.md body (ROADMAP Phase 16 W-7).

    Mirrors ``_workflow_auto_text`` section-for-section (same contract
    marker, same resume/durability rules, same read order) but never implies
    a git-tracked codebase — a `workdir`-kind pod blueprint (research,
    content, ops) has none.
    """
    wd = work_dir.strip() or "(none configured yet — ask the human for a working directory)"
    origin_line = f"- origin: `{origin}`\n" if origin.strip() else ""
    stack_line = f"- stack: {stack}\n" if stack.strip() else ""
    return (
        f"{_CONTRACT_MARKER}\n"
        f"# WORKFLOW_AUTO.md — {project} startup protocol\n\n"
        "_The runtime makes you re-read this file after every context reset. "
        "Read it top to bottom before doing anything else._\n\n"
        "## Your working directory\n"
        f"`{wd}`\n\n"
        "All real work happens **here** — a plain working directory, not a "
        "git-tracked codebase. Before any file operation, `cd` into it (or use "
        "absolute paths under it). Treat relative paths as relative to this root.\n\n"
        "## Resume before you greet\n"
        "A context reset wiped your working memory — not your job. **Before** you "
        f"reply, greet, or say there is nothing to do, open `{HEARTBEAT_FILE}`:\n"
        "- If `## Active Tasks` has any unchecked `- [ ]` step, you were interrupted "
        "**mid-task**. Pick up the next unchecked step and keep going — do not "
        "restart from scratch and do not announce you are idle.\n"
        "- Only when every task is checked off or removed are you actually idle.\n\n"
        "## Durability rule — how a task survives a reset\n"
        "The moment you accept work you can't finish in one reply (anything "
        f"multi-step, multi-file, or long-running), **write it to `{HEARTBEAT_FILE}` "
        "under `## Active Tasks` as a checklist _before you start_**, then tick "
        "steps off as you go. In-context plans and mental notes do **not** survive "
        "a context reset — only what is on disk does. An unwritten task is a task "
        "you will silently lose.\n\n"
        "## Read these, in order\n"
        f"1. `{HEARTBEAT_FILE}` — active tasks / pending decisions (always; obey the "
        "resume rule above before doing anything else).\n"
        "2. `SOUL.md` — who you are, your scope, and your safety rules.\n"
        "3. `MEMORY.md` — what this project **is** and durable facts about it "
        "(objective summary, current state).\n"
        "4. `memory/YYYY-MM-DD.md` — today's log (create it if missing, one file "
        "per day); read yesterday's only if the task needs prior context. Don't "
        "slurp the whole `memory/` dir.\n\n"
        '## Answering "what is this project about"\n'
        "Answer from **MEMORY.md → What this project is**: describe what the "
        "objective is and who it's for. Do **not** answer with your pod role, "
        "agent id, session key, or workspace paths — that is *your* scaffolding, "
        "not the project. If that section is still a placeholder, read any notes "
        "in the working directory first and fill it in before answering.\n\n"
        "## Working directory\n"
        f"{origin_line}"
        f"- path: `{wd}`\n"
        f"{stack_line}\n"
        "## If a file 'isn't found'\n"
        "You are almost certainly in the wrong directory — the agent workspace, "
        "not the working directory above. Re-check that you are under the "
        "working directory root **before** concluding the file does not exist or "
        "offering to create it.\n"
    )


def heartbeat_seed(name: str) -> str:
    """The durable task-ledger body for a fresh (or reset) ``HEARTBEAT.md``.

    Single source for every workspace's ledger — the CLI create/reset paths
    (``cli/_agents.py``) and pod provisioning (``cli/_pod.py``) all render this,
    so the resume/durability contract in ``WORKFLOW_AUTO.md`` always has a ledger
    shaped the way it describes. The embedded HTML comment is a fill-in template:
    invisible to a human reader, but it shows a weak model the exact task format
    so an accepted task gets written down consistently instead of held in context.
    """
    return (
        f"# {HEARTBEAT_FILE} — {name}\n\n"
        "_Your durable task ledger. It survives context resets; your working "
        "memory does not._\n"
        "_The moment you accept multi-step work, record it here **before** you "
        "start. Read it first every session — unchecked items mean you were "
        "interrupted, so resume them instead of greeting as if idle._\n\n"
        "## Active Tasks\n"
        "_none yet_\n\n"
        "<!-- When you accept a task, add it in this shape and work the checklist:\n"
        "### <short task title>  ·  started <YYYY-MM-DD>\n"
        'Goal: <what "done" looks like>\n'
        "- [ ] first step\n"
        "- [ ] next step\n"
        "Tick each `- [ ]` as you finish it. When the whole task is done, remove it\n"
        "here and log the outcome to memory/YYYY-MM-DD.md. -->\n\n"
        "## Pending Decisions\n"
        "_none_\n\n"
        "## Notes\n"
        "_none_\n"
    )


def _memory_md_seed(*, project: str, codebase: str, stack: str, work_dir: str = "") -> str:
    cb = codebase.strip()
    wd = work_dir.strip()
    lines = [
        f"# MEMORY.md — {project}",
        "",
        "_Long-term curated memory. Keep it lean — every byte is re-fed each "
        "session. Record durable facts, not day-to-day logs (those go in "
        "`memory/YYYY-MM-DD.md`)._",
        "",
        "## What this project is",
        f"_One paragraph: what {project} does and who it's for — the product, "
        "not this agent's pod role. Fill from the codebase README on first run; "
        'this is the answer to "what is this project about"._',
        "",
    ]
    # ROADMAP Phase 16 W-7: a `workdir`-kind pod blueprint has no codebase —
    # this branch never fires for an existing (codebase or none) caller.
    if wd:
        lines.append("## Working directory")
        lines.append(f"- path: `{wd}`")
    else:
        lines.append("## Repo")
        if cb:
            lines.append(f"- codebase: `{cb}`")
    if stack.strip():
        lines.append(f"- stack: {stack.strip()}")
    lines += [
        "",
        "## Architecture",
        "_Fill on first run: entry points, key modules, how it fits together._",
        "",
        "## Current state",
        "_What works, what's in flight, known issues._",
    ]
    return "\n".join(lines) + "\n"


def _daily_seed(
    *, project: str, codebase: str, stack: str, day: _dt.date, work_dir: str = ""
) -> str:
    lines = [
        f"# {day.isoformat()} — {project}",
        "",
        "_First working log, seeded at provisioning so the post-compaction audit "
        "passes on turn one. Append real session outcomes below._",
        "",
    ]
    # See _memory_md_seed's note: work_dir is the W-7 workdir-blueprint case;
    # an existing (codebase or neither) caller takes the unchanged elif/nothing path.
    if work_dir.strip():
        lines.append(f"- Working directory: `{work_dir.strip()}`")
    elif codebase.strip():
        lines.append(f"- Codebase: `{codebase.strip()}`")
    if stack.strip():
        lines.append(f"- Stack: {stack.strip()}")
    return "\n".join(lines) + "\n"


# --- seeding + healing --------------------------------------------------------


def contract_ok(ws: Path) -> bool:
    """True if *ws* satisfies the current runtime contract.

    Requires ``WORKFLOW_AUTO.md`` to exist **and** carry the current contract
    marker — so ``docket doctor`` re-seeds workspaces whose file is missing *or*
    stale/legacy, not just missing.
    """
    wf = ws / REQUIRED_STARTUP_FILE
    if not wf.is_file():
        return False
    try:
        return _CONTRACT_MARKER in wf.read_text(encoding="utf-8")
    except OSError:
        return False


def seed_contract(
    ws: Path,
    *,
    project: str,
    codebase: str = "",
    stack: str = "",
    origin: str = "",
    day: _dt.date | None = None,
    work_dir: str = "",
) -> None:
    """Create/refresh the files the openclaw post-compaction audit requires.

    Rewrites ``WORKFLOW_AUTO.md`` (derived — always refreshed). Creates
    ``MEMORY.md`` and today's ``memory/YYYY-MM-DD.md`` only if absent, so
    re-seeding never clobbers a real day's log or curated memory. Idempotent.
    Every file this function touches is normalized to ``0600`` (workspace files
    are owner-only, per the permissions invariant) whether freshly written or
    already present — so a doctor-driven heal also fixes stale permissions.

    ``work_dir`` (ROADMAP Phase 16 W-7): set for a `workdir`-kind pod
    blueprint (research/content/ops) instead of ``codebase`` — mutually
    exclusive with it. Leaving it unset (the default) reproduces every
    pre-W-7 caller's exact output.
    """
    d = day or today()
    memory_dir(ws).mkdir(parents=True, exist_ok=True)

    workflow_auto = ws / REQUIRED_STARTUP_FILE
    workflow_auto.write_text(
        _workflow_auto_text(
            project=project, codebase=codebase, stack=stack, origin=origin, work_dir=work_dir
        ),
        encoding="utf-8",
    )
    with contextlib.suppress(OSError):
        workflow_auto.chmod(0o600)

    mem_md = memory_md_path(ws)
    if not mem_md.exists():
        mem_md.write_text(
            _memory_md_seed(project=project, codebase=codebase, stack=stack, work_dir=work_dir),
            encoding="utf-8",
        )
    with contextlib.suppress(OSError):
        mem_md.chmod(0o600)

    daily = daily_log_path(ws, d)
    if not daily.exists():
        daily.write_text(
            _daily_seed(project=project, codebase=codebase, stack=stack, day=d, work_dir=work_dir),
            encoding="utf-8",
        )
    with contextlib.suppress(OSError):
        daily.chmod(0o600)
