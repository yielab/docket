"""Agent identity — the persona layer docket renders into SOUL.md.

docket owns an agent's identity as a pure function of its ``.docket-meta.json``
(see ``internal-docs/agent-structure-analysis.md`` §6). An agent's *role* is its
real identity; a **persona** (name/emoji/vibe) is an optional operator-assigned
skin on top. This module holds the pure string logic for rendering that persona
into ``SOUL.md`` and parsing an operator label — no I/O (the ``cli`` layer does
the file writes and gateway restart) — plus the one
I/O entry point that composes a turn's system prompt from this agent's own
on-disk identity files.

The persona lives in ``SOUL.md`` between HTML markers so it can be upserted
idempotently without disturbing the rest of the (role-derived) SOUL, and so a
just-reset agent reading SOUL sees a docket-controlled identity rather than a
self-authored ``IDENTITY.md``.

## The turn's system prompt

Without this module, ``core/agent_loop.py`` would compose no system prompt at all — ``SOUL.md``
(identity, scope, session key), the docket-owned persona, and
``WORKFLOW_AUTO.md``'s resume/durability contract (``core/memory.py``,
``CONTRACT_VERSION``) never reached the model. The same is true of the private
workspace state that contract names: HEARTBEAT/AGENTS/TOOLS/MEMORY are loaded
fresh here and appended by priority under the existing static-context budget.
That is not decoration: a just-reset agent cannot resume from a HEARTBEAT it
was told to find under project-tool roots that deliberately exclude its private
workspace.

``system_prompt_for_agent`` is the single function ``run_agent_turn`` calls,
once per turn. It re-reads the persona from ``.docket-meta.json`` rather than
trusting whatever ``SOUL.md`` already has upserted, because
``AgentMeta.display_name()`` is the one documented source of truth for a
display name (see ``core/models.py``) — folding the *live* persona in via
``upsert_persona_block`` (idempotent: a match is a no-op) means a persona
change is reflected on the very next turn even if something skipped
re-rendering the file. Nothing here is persisted back to session history —
composed fresh every turn, exactly like a live value should be, never stored
as a stale copy.
"""

from __future__ import annotations

from pathlib import Path

import docket.config as _cfg
from docket.core.memory import HEARTBEAT_FILE, MEMORY_FILE, REQUIRED_STARTUP_FILE
from docket.core.models import AgentMeta, Persona
from docket.edges import store as _store

PERSONA_BEGIN = "<!-- docket-persona:begin -->"
PERSONA_END = "<!-- docket-persona:end -->"

#: The identity file `system_prompt_for_agent` reads alongside
#: ``WORKFLOW_AUTO.md`` — kept as a local constant (not re-exported from
#: elsewhere) since no other module currently needs the bare filename.
SOUL_FILE = "SOUL.md"

_RUNTIME_CONTEXT_FILES = (HEARTBEAT_FILE, "AGENTS.md", "TOOLS.md", MEMORY_FILE)
_RUNTIME_CONTEXT_NOTE = (
    "# Runtime-loaded Docket workspace state\n"
    "These private control files are already loaded from the Docket workspace. "
    "Do not search for, recreate, or modify them with project tools; project tools remain "
    "rooted in the project workspace. Docket owns task durability for this turn."
)
_RUNTIME_CONTEXT_FOOTER = (
    "\n\n# Runtime workspace state loaded\n"
    "Continue with the assigned task now; do not call read/glob/write for these private "
    "control files."
)

#: Base-assistant scaffolding a self-authoring runtime may leave behind, and that
#: must not linger in a docket-managed
#: workspace. ``BOOTSTRAP.md`` ("you just woke up, figure out who you are") and the
#: empty ``IDENTITY.md`` ("pick a name") self-author a drifting identity that fights
#: the docket-generated, role-derived ``SOUL.md`` — the exact split-brain that made a
#: pod Lead behave like a free-roaming assistant. docket owns identity via metadata +
#: SOUL, so these are pollution to quarantine (see agent-structure-analysis.md §6).
SCAFFOLDING_FILES = ("IDENTITY.md", "BOOTSTRAP.md")


def quarantine_scaffolding(ws: Path) -> list[str]:
    """Move any base-assistant scaffolding in *ws* into ``.docket-archive/``.

    Returns the archived filenames (empty if none). **Reversible** — files are moved,
    not deleted — so it is safe to run on provisioning and in ``docket doctor``.
    Idempotent. Mirrors ``core/memory.py``'s ownership of on-disk *memory* layout:
    this module owns on-disk *identity* layout, so it does its own file I/O here.
    """
    archived: list[str] = []
    for name in SCAFFOLDING_FILES:
        src = ws / name
        if src.is_file():
            dest_dir = ws / ".docket-archive"
            dest_dir.mkdir(exist_ok=True)
            src.replace(dest_dir / name)
            archived.append(name)
    return archived


def parse_persona_label(label: str) -> Persona:
    """Parse an operator label like ``"Orion 🔭"`` into a :class:`Persona`.

    A trailing token containing no alphanumerics is taken as the emoji; the rest
    is the name. ``"Orion"`` → name only; ``"Orion 🔭"`` → name + emoji; ``""`` →
    an empty persona (used to signal "clear").
    """
    tokens = label.strip().split()
    if not tokens:
        return Persona()
    emoji = ""
    if len(tokens) > 1 and not any(c.isalnum() for c in tokens[-1]):
        emoji = tokens[-1]
        tokens = tokens[:-1]
    return Persona(name=" ".join(tokens), emoji=emoji)


def render_persona_block(persona: Persona | None) -> str:
    """The marked ``SOUL.md`` snippet for *persona* — ``""`` if no name set.

    Deliberately terse: it names the persona but reasserts that the role is the
    true identity, so a friendly name never dilutes the pod-role contract.
    """
    if persona is None or not persona.label():
        return ""
    vibe = f" — {persona.vibe}" if persona.vibe else ""
    return (
        f"{PERSONA_BEGIN}\n"
        "## Persona\n"
        f"You may present yourself as **{persona.label()}**{vibe}. That is a "
        "display name only — your real identity, scope, and rules are your role "
        "above. Do not invent a different name or self-author an identity file.\n"
        f"{PERSONA_END}"
    )


def upsert_persona_block(soul_text: str, persona: Persona | None) -> str:
    """Return *soul_text* with the persona block inserted, replaced, or removed.

    Idempotent: an existing block (matched by markers) is replaced or dropped; a
    new block is appended. Clearing (``persona`` None/empty) removes any block.
    """
    block = render_persona_block(persona)
    start = soul_text.find(PERSONA_BEGIN)
    if start != -1:
        end = soul_text.find(PERSONA_END, start)
        if end != -1:
            end += len(PERSONA_END)
            # Also swallow a single trailing newline pair to avoid blank buildup.
            head, tail = soul_text[:start].rstrip("\n"), soul_text[end:].lstrip("\n")
            if not block:
                return (head + "\n" + tail).rstrip("\n") + "\n" if tail else head + "\n"
            return f"{head}\n\n{block}\n\n{tail}".rstrip("\n") + "\n"
    if not block:
        return soul_text
    return soul_text.rstrip("\n") + "\n\n" + block + "\n"


# ── the turn's system prompt ────────────────────────────────────────────────


def compose_system_prompt(
    soul_text: str,
    workflow_auto_text: str,
    persona: Persona | None,
    runtime_context: str = "",
) -> str:
    """Fold SOUL.md, the live persona, and WORKFLOW_AUTO.md into one system prompt.

    Pure — no I/O, matching this module's own convention (``system_prompt_for_agent``
    below is the I/O entry point that calls this). *soul_text* is passed through
    ``upsert_persona_block`` so the persona reflects *persona* as given, not
    whatever ``SOUL.md`` happened to have on disk (see the module docstring);
    calling it unconditionally is safe even when *soul_text* is empty or already
    carries a matching block — both are idempotent no-ops.

    Empty inputs degrade gracefully: no ``SOUL.md`` and no ``WORKFLOW_AUTO.md``
    (an unprovisioned or misconfigured agent) composes to ``""``, which
    ``core/agent_loop.py`` treats as "no system message this turn" rather than
    sending the model an empty one.
    """
    effective_soul = upsert_persona_block(soul_text, persona).strip()
    workflow = workflow_auto_text.strip()
    runtime = runtime_context.strip()
    parts = [part for part in (effective_soul, workflow, runtime) if part]
    return "\n\n---\n\n".join(parts)


def _visible_truncate(text: str, max_bytes: int, label: str) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    if max_bytes <= 0:
        return ""

    marker = f"\n[... {label} truncated: {len(encoded)} bytes omitted ...]\n"
    marker_bytes = marker.encode("utf-8")
    if len(marker_bytes) >= max_bytes:
        return marker_bytes[:max_bytes].decode("utf-8", errors="ignore")

    content_bytes = max_bytes - len(marker_bytes)
    head_size = content_bytes // 2
    tail_size = content_bytes - head_size
    omitted = len(encoded) - head_size - tail_size
    marker = f"\n[... {label} truncated: {omitted} bytes omitted ...]\n"
    marker_bytes = marker.encode("utf-8")
    content_bytes = max(max_bytes - len(marker_bytes), 0)
    head_size = content_bytes // 2
    tail_size = content_bytes - head_size
    head = encoded[:head_size].decode("utf-8", errors="ignore")
    tail = encoded[-tail_size:].decode("utf-8", errors="ignore") if tail_size else ""
    return f"{head}{marker}{tail}"


def _runtime_workspace_context(ws: Path, base_prompt: str) -> str:
    """Fit freshly read private workspace state after mandatory identity context."""
    available_sections = [
        (name, text)
        for name in _RUNTIME_CONTEXT_FILES
        if (text := _read_workspace_text(ws / name).strip())
    ]
    if not available_sections:
        return ""

    max_bytes = _cfg.CONTEXT_TOKEN_BUDGET * _cfg.CONTEXT_BYTES_PER_TOKEN
    remaining = max_bytes - len(base_prompt.encode("utf-8"))
    if base_prompt:
        remaining -= len(b"\n\n---\n\n")
    prefix = _RUNTIME_CONTEXT_NOTE
    prefix_bytes = len(prefix.encode("utf-8"))
    footer_bytes = len(_RUNTIME_CONTEXT_FOOTER.encode("utf-8"))
    if remaining < prefix_bytes + footer_bytes:
        return ""

    parts = [prefix]
    remaining -= prefix_bytes + footer_bytes
    for name, text in available_sections:
        header = f"\n\n## {name}\n"
        header_bytes = len(header.encode("utf-8"))
        if remaining <= header_bytes:
            break
        parts.append(header)
        remaining -= header_bytes
        fitted = _visible_truncate(text, remaining, name)
        parts.append(fitted)
        used = len(fitted.encode("utf-8"))
        remaining -= used
        if fitted != text:
            break
    parts.append(_RUNTIME_CONTEXT_FOOTER)
    return "".join(parts)


def load_agent_persona(agent_id: str) -> Persona | None:
    """Read *agent_id*'s persona straight from ``.docket-meta.json``.

    The single source of truth ``AgentMeta.display_name()`` already reads
    from (``core/models.py``) — never derived from ``SOUL.md`` text. Never
    raises: a missing workspace, missing/malformed meta record, or an agent
    with no persona set all resolve to ``None``.
    """
    if not agent_id:
        return None
    raw = _store.read_json(_cfg.meta_path(agent_id))
    if not raw:
        return None
    try:
        return AgentMeta.model_validate(raw).persona
    except Exception:
        return None


def _read_workspace_text(path: Path) -> str:
    """Best-effort text read — ``""`` for a missing file or an unreadable one."""
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def system_prompt_for_agent(agent_id: str) -> str:
    """Read *agent_id*'s identity plus bounded private state and compose a prompt.

    The one I/O entry point ``core/agent_loop.py`` needs for prompt
    composition — everything else in this module stays pure.
    ``""`` for an agent with no workspace/identity files (e.g. an id docket has
    never provisioned) rather than raising: a turn must still be able to run
    with no identity to compose.
    """
    if not agent_id:
        return ""
    ws = _cfg.workspace_dir(agent_id)
    soul_text = _read_workspace_text(ws / SOUL_FILE)
    workflow_text = _read_workspace_text(ws / REQUIRED_STARTUP_FILE)
    persona = load_agent_persona(agent_id)
    base_prompt = compose_system_prompt(soul_text, workflow_text, persona)
    runtime_context = _runtime_workspace_context(ws, base_prompt)
    return compose_system_prompt(soul_text, workflow_text, persona, runtime_context)
