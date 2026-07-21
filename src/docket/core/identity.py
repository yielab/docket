"""Agent identity — the persona layer docket renders into SOUL.md.

docket owns an agent's identity as a pure function of its ``.docket-meta.json``
(see ``internal-docs/agent-structure-analysis.md`` §6). An agent's *role* is its
real identity; a **persona** (name/emoji/vibe) is an optional operator-assigned
skin on top. This module holds the pure string logic for rendering that persona
into ``SOUL.md`` and parsing an operator label — no I/O (the ``cli`` layer does
the file writes and gateway restart).

The persona lives in ``SOUL.md`` between HTML markers so it can be upserted
idempotently without disturbing the rest of the (role-derived) SOUL, and so a
just-reset agent reading SOUL sees a docket-controlled identity rather than a
self-authored ``IDENTITY.md``.
"""

from __future__ import annotations

from pathlib import Path

from docket.core.models import Persona

PERSONA_BEGIN = "<!-- docket-persona:begin -->"
PERSONA_END = "<!-- docket-persona:end -->"

#: OpenClaw base-assistant scaffolding that must not linger in a docket-managed
#: workspace. ``BOOTSTRAP.md`` ("you just woke up, figure out who you are") and the
#: empty ``IDENTITY.md`` ("pick a name") self-author a drifting identity that fights
#: the docket-generated, role-derived ``SOUL.md`` — the exact split-brain that made a
#: pod Lead behave like a free-roaming assistant. docket owns identity via metadata +
#: SOUL, so these are pollution to quarantine (see agent-structure-analysis.md §6).
SCAFFOLDING_FILES = ("IDENTITY.md", "BOOTSTRAP.md")


def quarantine_scaffolding(ws: Path) -> list[str]:
    """Move any OpenClaw base-assistant scaffolding in *ws* into ``.docket-archive/``.

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
