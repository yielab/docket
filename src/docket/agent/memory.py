"""Memory domain — the single owner of an agent's on-disk memory layout (paths, names, the
clock, the durability contract the turn loop relies on); CLI and provisioning callers never
re-derive paths or dates. See specs/functional/workspace-structure.spec.md for the artifact
layout and specs/functional/pod-dispatch.spec.md for the HEARTBEAT.md dispatch-ledger
reconciliation (``write_dispatch_tasks``/``sync_dispatch_tasks``,
``DISPATCH_BLOCK_BEGIN``/``_END``), and specs/functional/agent-loop.spec.md for how the turn
loop composes SOUL.md and a runtime-safe ``WORKFLOW_AUTO.md`` projection into the
system message every turn. What a pod learns by itself lives in ``teams/memory.py``; this
module keeps no daily log and distills nothing. One clock: all day math is **UTC**, matching
``.docket-meta.json``'s ``created`` and the trace/audit timestamps."""

from __future__ import annotations

import contextlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docket.kernel import text as _text

# --- turn-loop durability contract (keep in sync with agent_loop.py's prompt) -

#: The always-re-read startup file the runtime audits for.
REQUIRED_STARTUP_FILE = "WORKFLOW_AUTO.md"

#: Long-term curated memory document (runtime memory-backend root).
MEMORY_FILE = "MEMORY.md"

#: Durable task ledger (in-flight work that must survive a context reset).
HEARTBEAT_FILE = "HEARTBEAT.md"

#: Bumped when the generated WORKFLOW_AUTO.md body changes. Embedded as a marker
#: so ``docket setup --fix`` can detect and re-seed *stale* content, not just absence.
#: v3 adds the resume/durability contract (write in-flight tasks to HEARTBEAT.md
#: before starting; resume unchecked tasks on reset instead of greeting idle).
#: v4 adds a manual-path header: this file's `cd`/write-HEARTBEAT instructions
#: are for an agent reading it directly, outside Docket's own turn loop, which
#: never sends this raw text and applies its own read-only runtime contract
#: instead (`agent/identity.py`).
CONTRACT_VERSION = 4
_CONTRACT_MARKER = f"<!-- docket-contract: v{CONTRACT_VERSION} -->"

#: Shared by both `_workflow_auto_text` and `_workflow_auto_text_workdir`: this
#: file's own `cd`/write-HEARTBEAT instructions below are the manual-path
#: contract for an agent reading this file directly -- Docket's own turn loop
#: never sends this raw text and applies the live runtime contract instead.
_MANUAL_PATH_HEADER = (
    "**Manual-path contract.** Docket's own turn loop already applies this "
    "durability contract for you every turn and never sends you this raw file -- "
    "if you are running under Docket, you do not need to act on the "
    "instructions below yourself. They apply when this workspace is read "
    "directly, outside Docket's turn loop (a human-attached session, or another "
    "harness).\n\n"
)


# --- date + path canon (UTC everywhere) ---------------------------------------


def memory_dir(ws: Path) -> Path:
    return ws / "memory"


def memory_md_path(ws: Path) -> Path:
    return ws / MEMORY_FILE


# --- contract file bodies -----------------------------------------------------


def _workflow_auto_text(
    *, project: str, codebase: str, stack: str, origin: str, work_dir: str = ""
) -> str:
    # A `workdir`-kind pod blueprint (research/content/ops) has no codebase
    # at all — routing to a dedicated sibling function (rather than branching
    # mid-string here) keeps the codebase-flavored text below byte-for-byte
    # unchanged for every caller that passes work_dir="".
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
        f"{_MANUAL_PATH_HEADER}"
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
    """The `workdir`-flavored WORKFLOW_AUTO.md body: mirrors ``_workflow_auto_text``
    section-for-section (same contract marker, resume/durability rules, read order) but
    never implies a git-tracked codebase, since a `workdir`-kind pod blueprint has none."""
    wd = work_dir.strip() or "(none configured yet — ask the human for a working directory)"
    origin_line = f"- origin: `{origin}`\n" if origin.strip() else ""
    stack_line = f"- stack: {stack}\n" if stack.strip() else ""
    return (
        f"{_CONTRACT_MARKER}\n"
        f"# WORKFLOW_AUTO.md — {project} startup protocol\n\n"
        "_The runtime makes you re-read this file after every context reset. "
        "Read it top to bottom before doing anything else._\n\n"
        f"{_MANUAL_PATH_HEADER}"
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
    """The durable task-ledger body for a fresh (or reset) ``HEARTBEAT.md``: the single source
    every render path (CLI create/reset, pod provisioning) uses, so ``WORKFLOW_AUTO.md``'s
    resume/durability contract always finds a ledger shaped as described. The embedded HTML
    comment is a human-invisible fill-in template that shows a weak model the task format."""
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


def _memory_md_seed(*, project: str, stack: str) -> str:
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
    if stack.strip():
        lines += ["## Stack", f"- stack: {stack.strip()}", ""]
    lines += [
        "## Architecture",
        "_Fill on first run: entry points, key modules, how it fits together._",
        "",
        "## Current state",
        "_What works, what's in flight, known issues._",
    ]
    return "\n".join(lines) + "\n"


# --- seeding + healing --------------------------------------------------------


def contract_ok(ws: Path) -> bool:
    """True if *ws* satisfies the current runtime contract: ``WORKFLOW_AUTO.md`` must exist
    **and** carry the current contract marker, so ``docket setup --fix`` re-seeds a workspace whose
    file is missing *or* stale, not just missing."""
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
    work_dir: str = "",
) -> None:
    """Create/refresh the files the turn loop's system-prompt composition requires. Rewrites
    ``WORKFLOW_AUTO.md`` (derived, always refreshed); creates ``MEMORY.md`` only if absent, so
    re-seeding never clobbers the operator's notes, and an empty ``memory/``. Idempotent;
    every touched file is normalized to ``0600`` even when already present, so a doctor-driven
    heal also fixes stale permissions. ``work_dir`` (mutually exclusive with ``codebase``) is
    set for a `workdir`-kind pod blueprint; unset reproduces the codebase-flavored output."""
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
            _memory_md_seed(project=project, stack=stack),
            encoding="utf-8",
        )
    with contextlib.suppress(OSError):
        mem_md.chmod(0o600)


# --- dispatch task ledger --------------------------------------------------
#
# Design rationale: specs/functional/pod-dispatch.spec.md (dispatch ledger).
# Everything below is pure text/file manipulation over one
# workspace's HEARTBEAT.md -- docket-owned workspace state throughout,
# no ui/print (application code
# never prints), no knowledge of the TASK_LIST.json schema beyond
# the handful of plain dict keys `sync_dispatch_tasks` reads.

#: Delimiters bracketing the docket-owned dispatch region inside HEARTBEAT.md's
#: ``## Active Tasks`` section. Never rendered outside these two lines' worth
#: of markers, so a plain text search for either one is always safe.
DISPATCH_BLOCK_BEGIN = "<!-- docket:dispatch-tasks:start -->"
DISPATCH_BLOCK_END = "<!-- docket:dispatch-tasks:end -->"

_ACTIVE_TASKS_HEADING = "## Active Tasks"

#: Longest inline description in one mechanical ledger entry. Long enough to
#: be useful, short enough that a wall of task text never crowds out an
#: agent's own hand-written notes sharing the same file.
_DISPATCH_DESC_MAX = 200


@dataclass(frozen=True)
class DispatchHeartbeatTask:
    """One in-flight (``TASK_LIST.json`` ``status: "running"``) task, as rendered
    into HEARTBEAT.md's docket-owned dispatch region."""

    task_id: str
    description: str
    claimed_at: str
    hops: int = 0


def _dispatch_task_line(t: DispatchHeartbeatTask) -> str:
    desc = _text.one_line(t.description)  # collapse newlines/whitespace to one line
    desc = _text.ellipsize(desc, _DISPATCH_DESC_MAX)
    hop_word = "hop" if t.hops == 1 else "hops"
    claimed = t.claimed_at or "unknown time"
    return f"- [ ] {t.task_id} — {desc}  _(claimed {claimed}, {t.hops} {hop_word} run)_"


def render_dispatch_block(tasks: Sequence[DispatchHeartbeatTask]) -> str:
    """The exact text of the docket-owned dispatch region, delimiters included."""
    body = "\n".join(_dispatch_task_line(t) for t in tasks)
    middle = f"\n{body}\n" if body else "\n"
    return f"{DISPATCH_BLOCK_BEGIN}{middle}{DISPATCH_BLOCK_END}"


def write_dispatch_tasks(ws: Path, tasks: Sequence[DispatchHeartbeatTask]) -> None:
    """Mechanically upsert dispatch's docket-owned block into *ws*'s HEARTBEAT.md. Only text
    between ``DISPATCH_BLOCK_BEGIN``/``_END`` is ever replaced; every other byte (an agent's own
    entries, other sections) is preserved exactly — see specs/functional/pod-dispatch.spec.md for
    the co-authorship contract. A missing block is inserted after ``## Active Tasks`` (or a fresh
    heading appended if even that is missing); a missing HEARTBEAT.md is seeded first via
    :func:`heartbeat_seed`. Idempotent (byte-identical on repeat calls) and normalized to 0600."""
    ws.mkdir(parents=True, exist_ok=True)
    path = ws / HEARTBEAT_FILE
    text = path.read_text(encoding="utf-8") if path.is_file() else heartbeat_seed(ws.name)
    block = render_dispatch_block(tasks)

    if DISPATCH_BLOCK_BEGIN in text and DISPATCH_BLOCK_END in text:
        start = text.index(DISPATCH_BLOCK_BEGIN)
        end = text.index(DISPATCH_BLOCK_END) + len(DISPATCH_BLOCK_END)
        new_text = text[:start] + block + text[end:]
    else:
        idx = text.find(_ACTIVE_TASKS_HEADING)
        if idx != -1:
            insert_at = idx + len(_ACTIVE_TASKS_HEADING)
            nl = text.find("\n", insert_at)
            insert_at = nl + 1 if nl != -1 else len(text)
            new_text = f"{text[:insert_at]}\n{block}\n{text[insert_at:]}"
        else:
            sep = "" if text.endswith("\n") else "\n"
            new_text = f"{text}{sep}\n{_ACTIVE_TASKS_HEADING}\n\n{block}\n"

    if path.is_file() and new_text == text:
        return  # already exactly this state -- skip the needless write/mtime bump
    path.write_text(new_text, encoding="utf-8")
    with contextlib.suppress(OSError):
        path.chmod(0o600)


def read_dispatch_task_ids(ws: Path) -> list[str]:
    """Task ids currently recorded in *ws*'s HEARTBEAT.md dispatch region. ``[]`` when the file
    is absent, unreadable, or has no dispatch region yet; ``docket setup --fix`` diffs this against
    ``TASK_LIST.json``'s ``running`` ids to detect ledger drift (``_check_dispatch_ledger``)."""
    path = ws / HEARTBEAT_FILE
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if DISPATCH_BLOCK_BEGIN not in text or DISPATCH_BLOCK_END not in text:
        return []
    start = text.index(DISPATCH_BLOCK_BEGIN) + len(DISPATCH_BLOCK_BEGIN)
    end = text.index(DISPATCH_BLOCK_END)
    ids: list[str] = []
    for line in text[start:end].splitlines():
        line = line.strip()
        if not line.startswith("- [ ]"):
            continue
        rest = line[len("- [ ]") :].strip()
        task_id = rest.split(" ", 1)[0]
        if task_id:
            ids.append(task_id)
    return ids


def sync_dispatch_tasks(ws: Path, task_records: Iterable[Mapping[str, Any]]) -> None:
    """Regenerate *ws*'s dispatch ledger from a pod's TASK_LIST.json task dicts. Filters to
    ``status == "running"``, the only state where a hop is genuinely in flight; every other
    status means nothing to hold open. Called by both ``tasks/application/`` (at each
    task-state-persistence point) and ``docket setup --fix`` to re-sync a drifted ledger —
    always safe since ``TASK_LIST.json`` is dispatch's source of truth and the ledger's
    dispatch region is entirely docket-owned."""
    tasks = sorted(
        (
            DispatchHeartbeatTask(
                task_id=str(t["id"]),
                description=str(t.get("description", "")),
                claimed_at=str(t.get("claimedAt", "") or ""),
                hops=len(t.get("hops") or []),
            )
            for t in task_records
            if isinstance(t, Mapping) and t.get("status") == "running" and t.get("id")
        ),
        key=lambda t: t.task_id,
    )
    write_dispatch_tasks(ws, tasks)
