"""Pod memory grammar -- the reply's ``## Memory`` section and the checks on one line.

``parse_memory_section`` reads the bullets of a reply's trailing memory section;
``_vet`` says whether a bullet can be an entry at all (its subject, its note's length and tone).
Nothing here reads the task or the store. See specs/functional/workspace-structure.spec.md
"Pod memory"."""

from __future__ import annotations

import re
from dataclasses import dataclass

from docket.kernel.home import current_home

KINDS: tuple[str, ...] = ("generated", "command", "pitfall", "convention")
MEMORY_HEADING = "## Memory"

_BULLET = re.compile(r"^-\s+([A-Za-z]+):\s+(.+?)\s+--\s+(.+?)\s*$")
_URL = re.compile(r"https?://|\bwww\.", re.IGNORECASE)
_INSTRUCTION_PHRASES = re.compile(
    r"\b(ignore|disregard|override|forget|always|never|must|should|you|your|instructions?)\b"
    r"|\bdo not\b|\bdon'?t\b|\bfrom now on\b|\bsystem prompt\b",
    re.IGNORECASE,
)
_IMPERATIVE_FIRST_WORDS = frozenset(
    [
        "run",
        "use",
        "call",
        "execute",
        "delete",
        "remove",
        "write",
        "read",
        "send",
        "fetch",
        "download",
        "install",
        "push",
        "pull",
        "curl",
        "wget",
        "ignore",
        "disregard",
        "override",
        "always",
        "never",
        "do",
        "don't",
        "dont",
        "make",
        "ensure",
        "change",
        "edit",
        "open",
        "skip",
        "avoid",
        "prefer",
        "apply",
        "create",
        "rename",
        "replace",
        "enable",
        "disable",
        "allow",
        "approve",
        "grant",
        "reveal",
        "print",
        "tell",
        "paste",
        "follow",
        "obey",
        "treat",
        "assume",
        "pretend",
        "forget",
        "remember",
        "try",
        "merge",
        "commit",
        "add",
        "fix",
        "keep",
        "put",
        "take",
        "look",
        "go",
        "be",
        "let",
    ]
)


@dataclass(frozen=True)
class ParsedLine:
    """One bullet of a reply's memory section; ``refusal`` is set when it fits no entry."""

    kind: str
    subject: str
    note: str
    refusal: str = ""


# -- the reply's memory section --------------------------------------------------


def parse_memory_section(text: str) -> list[ParsedLine]:
    """The entries of *text*'s trailing ``## Memory`` section (the last such heading wins; it
    ends at the next heading). Prose lines are ignored, a bullet outside the grammar or naming
    another kind is returned with a ``refusal``; at most ``POD_MEMORY_MAX_PER_TASK`` come back."""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.strip().lower() == MEMORY_HEADING.lower()]
    if not starts:
        return []
    parsed: list[ParsedLine] = []
    for raw in lines[starts[-1] + 1 :]:
        line = raw.strip()
        if line.startswith("#"):
            break
        if not line.startswith("- "):
            continue
        if len(parsed) >= current_home().pod_memory_max_per_task:
            break
        match = _BULLET.match(line)
        if match is None:
            parsed.append(
                ParsedLine("", "", line[:80], "not of the form '- <kind>: <subject> -- <note>'")
            )
            continue
        kind = match.group(1).lower()
        subject = match.group(2).strip().strip("`").strip()
        if kind not in KINDS:
            parsed.append(ParsedLine(kind, subject, match.group(3), f"unknown kind '{kind[:20]}'"))
            continue
        parsed.append(ParsedLine(kind, subject, match.group(3).strip()))
    return parsed


def _safe_path(subject: str) -> str:
    """*subject* as a normalised repository-relative path, or ``""`` when it is not one."""
    path = subject[:-1] if subject.endswith("/") and len(subject) > 1 else subject
    if (
        not path
        or len(path) > current_home().pod_memory_note_max_chars
        or any(ord(c) < 32 for c in path)
    ):
        return ""
    if path == ".":
        return path
    if path.startswith(("/", "~")) or "\\" in path:
        return ""
    return path if all(part not in ("", ".", "..") for part in path.split("/")) else ""


def _reads_as_instruction(text: str) -> str:
    words = re.findall(r"[A-Za-z']+", text.lower())
    if _URL.search(text):
        return "contains a link"
    if words and words[0] in _IMPERATIVE_FIRST_WORDS:
        return "starts with an imperative verb"
    if _INSTRUCTION_PHRASES.search(text):
        return "reads as an instruction"
    return ""


def _vet(line: ParsedLine) -> tuple[str, str]:
    """``(subject, refusal)``: the normalised subject and why the line cannot be an entry."""
    subject = line.subject
    if line.kind != "command":
        subject = _safe_path(subject)
        if not subject:
            return line.subject[:200], "not a repository-relative path"
    elif not subject or len(subject) > current_home().pod_memory_note_max_chars:
        return subject[:200], "not a command of a reasonable length"
    if len(line.note) > current_home().pod_memory_note_max_chars:
        return subject, f"note over {current_home().pod_memory_note_max_chars} characters"
    if line.kind == "command" and _URL.search(subject):
        return subject, "contains a link"
    return subject, _reads_as_instruction(line.note)
