"""Memory domain — the single owner of an agent's on-disk memory layout.

Every fact about *where* memory lives, *what* it is named, *which clock* names
it, and *what durability contract the turn loop relies on* lives here. The CLI
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
                             Its ``## Active Tasks`` section also carries a
                             delimited, docket-owned region a pod dispatch
                             mechanically keeps in sync with the pod's
                             ``TASK_LIST.json`` — see "The dispatch task
                             ledger" below.
- ``memory/.distilled/``    — archive of daily logs a ``distill_memory`` call
                             has already summarized into ``MEMORY.md``, one
                             dated subdirectory per run. Never read by the
                             runtime contract; exists purely so ``maintain
                             clean``/``reset --distill-first`` can *move* a
                             log out of the way instead of deleting it
                             outright (see "Memory distillation" below).

## The dispatch task ledger

The resume/durability contract above tells the agent to hand-maintain
``HEARTBEAT.md``'s ``## Active Tasks`` list — which, left on its own, is only
ever as honest as an LLM's compliance, while ``TASK_LIST.json``
(``core/dispatch.py``) is the *actual* machine-read/written queue. The two would
otherwise never be reconciled, so dispatch writes its own record of in-flight work
mechanically: ``write_dispatch_tasks``/``sync_dispatch_tasks`` upsert a
delimited region (``DISPATCH_BLOCK_BEGIN``/``_END``) inside ``## Active
Tasks``, containing exactly the tasks ``TASK_LIST.json`` currently has
``status: "running"`` — true whether or not the agent ever wrote anything
there itself. Everything outside those two HTML-comment delimiters (an
agent's own prose anywhere in the file, including its own entries under the
same heading) is preserved byte-for-byte — see ``write_dispatch_tasks``'s own
docstring for the co-authorship mechanics. ``core/dispatch.py``'s
``_claim_next_task``/``_persist_hop``/``_touch_claim``/``_finalize_task``
call ``sync_dispatch_tasks`` at each of those lifecycle points; ``docket
doctor`` calls ``read_dispatch_task_ids`` to detect drift against
``TASK_LIST.json`` and the same ``sync_dispatch_tasks`` to fix it.

## Memory distillation

``distill_memory`` is docket's first *self-originated* LLM call: docket asks
an agent to summarize its own daily logs into ``MEMORY.md`` before
``maintain clean``/``reset`` would otherwise delete them outright. The call
goes **through the driver** (``RuntimeDriver.run_turn``, the same
port every pod dispatch hop already uses) — never a hand-rolled provider
SDK/HTTP client. The driver is injected as a plain callable (mirroring
``core/dispatch.py``'s own ``Runner`` alias, for the same reason:
``tests/python/fakes.py``'s ``FakeDriver`` is directly callable with that
signature, so this module is fully unit-testable with no real driver call).
``distill_memory`` fails **closed**: any driver failure or empty reply leaves
every file on disk untouched, so a caller gating a delete on
``DistillResult.ok`` never bare-deletes memory it could not verify was
captured somewhere durable first.

## The runtime contract

``core/agent_loop.py``'s own turn loop (via ``core.identity.system_prompt_for_agent``)
composes ``SOUL.md``, the live persona, and ``WORKFLOW_AUTO.md`` into the
system message on **every** turn, unconditionally — not a nag after the
fact, an input the model cannot skip reading. docket is still the
provisioner, so it must make these files *exist* and stay current;
``WORKFLOW_AUTO.md`` remains where we anchor the codebase path and the read
order so they survive compaction even when ``SOUL.md``/``MEMORY.md`` fall
out of the message history proper.

One clock: all day math is **UTC**, matching ``.docket-meta.json`` ``created``
and the trace/audit timestamps, so docket never disagrees with itself about
which daily file is "today" across a local-midnight boundary.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import docket.config as _cfg
from docket.core.runtime_driver import FailureKind, TurnResult

# --- turn-loop durability contract (keep in sync with agent_loop.py's prompt) -

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
    """The `workdir`-flavored WORKFLOW_AUTO.md body.

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
    # A `workdir`-kind pod blueprint has no codebase — this branch never
    # fires for a caller passing only `codebase` (or neither).
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
    # See _memory_md_seed's note: work_dir is the workdir-blueprint case; a
    # caller passing only codebase (or neither) takes the elif/nothing path.
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
    """Create/refresh the files the turn loop's system-prompt composition requires.

    Rewrites ``WORKFLOW_AUTO.md`` (derived — always refreshed). Creates
    ``MEMORY.md`` and today's ``memory/YYYY-MM-DD.md`` only if absent, so
    re-seeding never clobbers a real day's log or curated memory. Idempotent.
    Every file this function touches is normalized to ``0600`` (workspace files
    are owner-only, per the permissions invariant) whether freshly written or
    already present — so a doctor-driven heal also fixes stale permissions.

    ``work_dir``: set for a `workdir`-kind pod
    blueprint (research/content/ops) instead of ``codebase`` — mutually
    exclusive with it. Leaving it unset (the default) reproduces the
    codebase-flavored output unchanged.
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


# --- distillation ---------------------------------------------------------
#
# See the module docstring's "Memory distillation" section for the design
# rationale. Everything below is pure I/O over one workspace plus one
# injected driver call — no ui/print (this is
# core/, per the standing layer rule), no import of edges/adapters/ at all.

#: Subdirectory (under ``memory/``) that archived, already-distilled daily
#: logs are moved into. A dated subdirectory per ``distill_memory`` call. A
#: plain non-recursive ``memory/*.md`` glob (what ``maintain clean``/``reset``
#: used to delete outright) never descends into it, so an already-distilled
#: log can never be "found" and re-distilled or re-deleted by mistake.
DISTILLED_ARCHIVE_DIRNAME = ".distilled"

#: A daily-log line with this prefix is a compact, operator-authored invariant.
#: The prose summary remains model-owned; these sparse records are validated
#: mechanically and carried verbatim so identifiers, constants, and formulas
#: cannot silently drift during summarization.
EXACT_RECORD_PREFIX = "- [exact] "

#: The shape `distill_memory` needs from a driver: `run_turn`'s core 5-arg
#: call, nothing more. Mirrors ``core/dispatch.py``'s own ``Runner`` alias
#: (a plain ``Callable``, not the full ``RuntimeDriver`` Protocol) for the
#: identical reason: there is no OS process here for a caller to track or
#: cancel, so the Protocol's ``on_spawn`` keyword has nothing to attach to,
#: and dropping it is what lets both ``DocketDriver.run_turn`` (a bound
#: method) and ``tests/python/fakes.py``'s ``FakeDriver`` (directly, as a
#: callable instance) satisfy this type with zero adapter code.
DistillRunner = Callable[[str, str, str, int, dict[str, str] | None], TurnResult]


@dataclass
class DistillResult:
    """Outcome of one ``distill_memory`` call.

    ``ok=False`` means memory was left **completely untouched** — no archive
    directory created, no ``MEMORY.md`` write, no daily log moved. That is
    the fail-closed contract ``maintain clean``/``reset --distill-first``
    depends on: a caller MUST NOT proceed to its own destructive step unless
    ``ok`` is True. ``skipped`` (only ever True alongside ``ok=True``) means
    there was nothing to distill — no pending daily logs — which is also a
    green light to proceed, since there is no undistilled memory to lose.
    """

    ok: bool
    skipped: bool = False
    logs_distilled: int = 0
    archived: list[str] = field(default_factory=list)
    summary: str = ""
    error: str = ""
    failure_kind: FailureKind | None = None


def pending_daily_logs(ws: Path) -> list[Path]:
    """Daily ``memory/*.md`` logs not yet archived, oldest filename first.

    A plain (non-recursive) glob already excludes anything under
    ``memory/.distilled/`` — worth stating explicitly: a second ``distill``
    call the same day only ever sees genuinely new logs.
    """
    mem = memory_dir(ws)
    if not mem.is_dir():
        return []
    return sorted(p for p in mem.glob("*.md") if p.is_file())


def _distillation_message(label: str, logs: list[Path]) -> str:
    """Build the one-turn distillation prompt from *logs*' own content.

    Each log's text is inlined directly into the prompt (rather than relying
    on the target agent to re-read files from its own workspace), so the
    driver call is self-contained and deterministic — a fake driver in a
    test can assert on exactly what was asked without touching a filesystem
    itself. Bounded by ``config.DISTILL_MAX_INPUT_BYTES``: logs are added
    oldest-first until the budget is spent, then truncated with an explicit
    marker rather than silently cut off.
    """
    header = (
        f"You are distilling durable memory for '{label}'. Below are daily "
        "working logs (memory/YYYY-MM-DD.md), oldest first. Read them and "
        "write a concise, durable summary suitable for appending to "
        "MEMORY.md: keep facts that matter long-term (decisions, "
        "architecture, open issues, durable state); drop day-to-day "
        "narration and anything already captured elsewhere. Lines beginning "
        f"with `{EXACT_RECORD_PREFIX}` are exact durable records: preserve their "
        "decision identifier and every backtick-delimited literal byte-for-byte; "
        "never rewrite their arithmetic, paths, versions, or quoted constants. Reply with the "
        "summary text only -- no preamble, no repeating the raw logs "
        "verbatim.\n"
    )
    budget = _cfg.DISTILL_MAX_INPUT_BYTES
    parts = [header]
    used = len(header.encode("utf-8"))
    for p in logs:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            text = ""
        chunk = f"\n--- {p.name} ---\n{text}"
        chunk_bytes = chunk.encode("utf-8")
        if used + len(chunk_bytes) > budget:
            remaining = max(0, budget - used)
            parts.append(chunk_bytes[:remaining].decode("utf-8", errors="ignore"))
            parts.append(
                "\n\n[... truncated: remaining logs exceeded the distillation byte budget ...]\n"
            )
            break
        parts.append(chunk)
        used += len(chunk_bytes)
    return "".join(parts)


def _exact_durable_records(logs: list[Path]) -> list[str]:
    """Return unique operator-marked records in source order, without their marker."""
    records: list[str] = []
    for path in logs:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(EXACT_RECORD_PREFIX):
                record = stripped.removeprefix(EXACT_RECORD_PREFIX).strip()
                if record and record not in records:
                    records.append(record)
    return records


def _summary_preserves_exact_records(summary: str, records: list[str]) -> bool:
    """Check the compact machine-verifiable parts of every exact record."""
    for record in records:
        identifier_match = re.search(r"\b[A-Z][A-Z0-9]*-\d+\b", record)
        identifier = identifier_match.group(0) if identifier_match else ""
        literals = re.findall(r"`([^`]+)`", record)
        if (identifier and identifier not in summary) or any(
            f"`{literal}`" not in summary for literal in literals
        ):
            return False
    return True


def _append_exact_records(summary: str, records: list[str]) -> str:
    if not records:
        return summary
    rendered = "\n".join(f"- {record}" for record in records)
    return f"{summary}\n\n## Exact durable records\n\n{rendered}"


def _append_distilled_summary(ws: Path, summary: str, day: _dt.date) -> None:
    """Append *summary* to ``MEMORY.md`` under a dated heading; create if absent."""
    mem_md = memory_md_path(ws)
    existing = ""
    if mem_md.is_file():
        with contextlib.suppress(OSError):
            existing = mem_md.read_text(encoding="utf-8")
    if existing and not existing.endswith("\n"):
        existing += "\n"
    section = f"\n## Distilled {day.isoformat()}\n\n{summary}\n"
    mem_md.write_text(
        existing + section if existing else f"# MEMORY.md\n{section}", encoding="utf-8"
    )
    with contextlib.suppress(OSError):
        mem_md.chmod(0o600)


def _archive_daily_logs(ws: Path, logs: list[Path], day: _dt.date) -> list[str]:
    """Move *logs* into ``memory/.distilled/<day>/``; return workspace-relative paths."""
    archive_dir = memory_dir(ws) / DISTILLED_ARCHIVE_DIRNAME / day.isoformat()
    archive_dir.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        archive_dir.chmod(0o700)
    moved: list[str] = []
    for log in logs:
        dest = archive_dir / log.name
        if dest.exists():
            stamp = _dt.datetime.now(_dt.UTC).strftime("%H%M%S%f")
            dest = archive_dir / f"{log.stem}-{stamp}{log.suffix}"
        log.rename(dest)
        with contextlib.suppress(OSError):
            dest.chmod(0o600)
        moved.append(str(dest.relative_to(ws)))
    return moved


def distill_memory(
    ws: Path,
    *,
    label: str,
    agent_id: str,
    session_key: str,
    driver: DistillRunner,
    timeout: int | None = None,
    day: _dt.date | None = None,
) -> DistillResult:
    """Summarize pending ``memory/*.md`` logs into ``MEMORY.md`` via one driver turn.

    This is docket's first self-originated LLM call: the summarization turn
    runs through the injected driver exactly like a pod dispatch hop, never
    a hand-rolled provider client.
    *agent_id*/*session_key* identify whose session runs the turn —
    in practice the workspace's own agent, already either a pod's Lead or an
    org-specialist utility agent, both of which already own their own
    memory (see the module docstring).

    Fails closed: any driver failure (timeout, daemon error, non-zero exit)
    or an empty/unusable reply leaves **every file on disk untouched** — no
    archive directory, no ``MEMORY.md`` write — and returns ``ok=False``.
    This is the whole point of ``--distill-first``: a caller must never
    delete the daily logs this call was supposed to capture if the capture
    itself failed.

    Nothing to distill (no pending daily logs) short-circuits to
    ``ok=True, skipped=True`` *before* any driver call is made — there is
    nothing undistilled to lose, so a caller may proceed with whatever
    destructive step it was about to take.
    """
    logs = pending_daily_logs(ws)
    if not logs:
        return DistillResult(ok=True, skipped=True)

    message = _distillation_message(label, logs)
    turn_timeout = timeout if timeout is not None else _cfg.DISTILL_TIMEOUT_S
    result = driver(agent_id, session_key, message, turn_timeout, None)
    if not result.ok:
        return DistillResult(
            ok=False,
            error=result.error or "distillation turn failed",
            failure_kind=result.failure_kind,
        )

    summary = result.output.strip()
    if not summary:
        return DistillResult(
            ok=False,
            error="distillation turn returned an empty summary",
            failure_kind="invalid_output",
        )

    exact_records = _exact_durable_records(logs)
    if not _summary_preserves_exact_records(summary, exact_records):
        return DistillResult(
            ok=False,
            error="distillation turn corrupted or omitted an exact durable record",
            failure_kind="invalid_output",
        )
    summary = _append_exact_records(summary, exact_records)

    d = day or today()
    _append_distilled_summary(ws, summary, d)
    archived = _archive_daily_logs(ws, logs, d)
    return DistillResult(ok=True, logs_distilled=len(logs), archived=archived, summary=summary)


# --- dispatch task ledger --------------------------------------------------
#
# See the module docstring's "The dispatch task ledger" section for the design
# rationale. Everything below is pure text/file manipulation over one
# workspace's HEARTBEAT.md -- docket-owned workspace state throughout,
# no ui/print (core/
# never prints), no knowledge of dispatch.py's TASK_LIST.json schema beyond
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
    desc = " ".join(t.description.split())  # collapse newlines/whitespace to one line
    if len(desc) > _DISPATCH_DESC_MAX:
        desc = desc[: _DISPATCH_DESC_MAX - 1] + "…"
    hop_word = "hop" if t.hops == 1 else "hops"
    claimed = t.claimed_at or "unknown time"
    return f"- [ ] {t.task_id} — {desc}  _(claimed {claimed}, {t.hops} {hop_word} run)_"


def render_dispatch_block(tasks: Sequence[DispatchHeartbeatTask]) -> str:
    """The exact text of the docket-owned dispatch region, delimiters included."""
    body = "\n".join(_dispatch_task_line(t) for t in tasks)
    middle = f"\n{body}\n" if body else "\n"
    return f"{DISPATCH_BLOCK_BEGIN}{middle}{DISPATCH_BLOCK_END}"


def write_dispatch_tasks(ws: Path, tasks: Sequence[DispatchHeartbeatTask]) -> None:
    """Mechanically upsert dispatch's docket-owned block into *ws*'s HEARTBEAT.md.

    Co-authorship contract: only the text between ``DISPATCH_BLOCK_BEGIN`` and
    ``DISPATCH_BLOCK_END`` is ever replaced. The first time this runs against a
    file with no such block yet, one is inserted immediately after the
    ``## Active Tasks`` heading (falling back to appending a fresh heading +
    block at end-of-file if that heading is missing entirely — a heavily
    hand-edited HEARTBEAT.md). Every other byte — an agent's own entries under
    that same heading, ``## Pending Decisions``, ``## Notes``, anything else in
    the file — is preserved exactly. Creates HEARTBEAT.md from
    :func:`heartbeat_seed` first if the workspace doesn't have one yet (e.g. a
    task claimed before provisioning finished writing it). Idempotent: calling
    twice with the same *tasks* leaves the file byte-identical the second
    time. Normalized to 0600, matching every other workspace file this module
    writes.
    """
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
    """Task ids currently recorded in *ws*'s HEARTBEAT.md dispatch region.

    ``[]`` when the file is absent, unreadable, or has no dispatch region yet
    (a workspace predating the dispatch ledger, or one dispatch has never
    claimed a task in) — the
    shape ``docket doctor`` diffs against ``TASK_LIST.json``'s own ``running``
    task ids to detect ledger drift (see ``cli/_doctor.py``'s
    ``_check_dispatch_ledger``).
    """
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
    """Regenerate *ws*'s dispatch ledger from a pod's TASK_LIST.json task dicts.

    Filters to ``status == "running"`` — the only state where a hop is
    genuinely in flight; every other status (``pending``/``done``/``failed``/
    ``blocked``/``waiting_approval``) means no hop is currently executing for
    that task, so there is nothing to hold open in the ledger for it. This is
    the one function both dispatch and doctor call: ``core/dispatch.py``'s
    ``_claim_next_task``/``_persist_hop``/``_touch_claim``/``_finalize_task``
    call it at each task-state-persistence point, and ``docket doctor``'s
    ``--fix`` calls it to re-sync a workspace whose ledger has drifted —
    always safe, since ``TASK_LIST.json`` is dispatch's own source of truth
    and the ledger's dispatch region is entirely docket-owned.
    """
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
