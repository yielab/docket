#!/usr/bin/env python3
"""Emit a bounded, deterministic Docket development context snapshot."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


def _git(root: Path, *args: str) -> str | None:
    """Return Git stdout, preserving probe failure as an unknown state."""

    try:
        result = subprocess.run(
            ["git", *args], cwd=root, check=False, capture_output=True, text=True, timeout=3
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _default_root() -> Path:
    """Use the containing Git root, or the current directory outside Git."""

    discovered = _git(Path.cwd(), "rev-parse", "--show-toplevel")
    return Path(discovered).resolve() if discovered else Path.cwd().resolve()


def _status_kind(body: str) -> str:
    match = re.search(r"^\*\*Status:\*\*\s*([^·\n]+)", body, flags=re.MULTILINE)
    if match is None:
        return "unknown"
    status = match.group(1).strip().upper()
    if status.startswith(("DONE", "COMPLETE", "CLOSED")):
        return "closed"
    if status.startswith(("IN PROGRESS", "IN-PROGRESS")):
        return "in_progress"
    if status.startswith(("TODO", "READY")):
        return "ready"
    if status.startswith("BLOCKED"):
        return "blocked"
    return "unknown"


def _board_summary(root: Path) -> tuple[str, dict[str, list[str]], int]:
    path = root / "TODO.md"
    if not path.is_file():
        return "TODO.md missing", {}, 0
    text = path.read_text(encoding="utf-8")
    board_headings = list(re.finditer(r"^(?:>\s*)?## (?:▶|◉|☑) .+$", text, flags=re.MULTILINE))
    if not board_headings:
        return "no unambiguous current board marker found", {}, 0
    first_h2 = re.search(r"^(?:>\s*)?## .+$", text, flags=re.MULTILINE)
    if first_h2 is None or first_h2.start() != board_headings[0].start():
        return "no unambiguous current board marker found", {}, 0

    def marker_kind(match: re.Match[str]) -> str:
        heading = match.group(0)
        if "☑" in heading and "BOARD CLEAR" in heading.upper():
            return "clear"
        if ("▶" in heading or "◉" in heading) and re.search(
            r"\b(ACTIVE|IN[ -]PROGRESS)\b", heading, flags=re.IGNORECASE
        ):
            return "active"
        return "historical"

    first_kind = marker_kind(board_headings[0])
    if first_kind == "clear":
        label = re.sub(r"^(?:>\s*)?##\s+", "", board_headings[0].group(0)).strip()
        return label, {}, 0
    if first_kind != "active":
        return "no unambiguous current board marker found", {}, 0

    def wave_key(match: re.Match[str]) -> str | None:
        key = re.search(r"\bWAVE\s+([A-Z0-9-]+)\b", match.group(0), flags=re.IGNORECASE)
        return key.group(1).upper() if key is not None else None

    # The repository's current board has a short ACTIVE BOARD banner followed
    # by one detailed heading for the same numbered wave, with only the usage
    # guide between them. Require all three signals; otherwise remain on the
    # first marker so an archived ACTIVE heading cannot become executable work.
    active_group = [board_headings[0]]
    first_heading = board_headings[0]
    first_key = wave_key(first_heading)
    if "ACTIVE BOARD" in first_heading.group(0).upper() and first_key is not None:
        for heading in board_headings[1:]:
            kind = marker_kind(heading)
            heading_key = wave_key(heading)
            if kind == "historical" and heading_key != first_key:
                normalized = heading.group(0).upper()
                if "☑" in normalized and "COMPLETE" in normalized:
                    continue
                break
            if kind != "active" or heading_key != first_key:
                break
            between = text[active_group[-1].end() : heading.start()]
            interstitial_h2 = re.findall(r"^(?:>\s*)?## (.+)$", between, flags=re.MULTILINE)
            if any(
                not (
                    title.upper().startswith("HOW TO USE THIS BOARD")
                    or (
                        "☑" in title
                        and "COMPLETE" in title.upper()
                        and re.search(r"\bWAVE\s+", title, flags=re.IGNORECASE)
                    )
                )
                for title in interstitial_h2
            ):
                break
            active_group.append(heading)
            break

    active = active_group[0]
    for candidate in active_group:
        following_h2 = re.search(r"^(?:>\s*)?## .+$", text[candidate.end() :], flags=re.MULTILINE)
        candidate_end = (
            candidate.end() + following_h2.start() if following_h2 is not None else len(text)
        )
        if re.search(r"^### .+$", text[candidate.end() : candidate_end], flags=re.MULTILINE):
            active = candidate

    next_heading = re.search(r"^(?:>\s*)?## .+$", text[active.end() :], flags=re.MULTILINE)
    end = active.end() + next_heading.start() if next_heading is not None else len(text)
    section = text[active.end() : end]
    card_headings = list(re.finditer(r"^### (.+)$", section, flags=re.MULTILINE))
    cards: dict[str, list[str]] = {
        "in_progress": [],
        "ready": [],
        "blocked": [],
        "unknown": [],
    }
    closed = 0
    for index, heading in enumerate(card_headings):
        card_end = (
            card_headings[index + 1].start() if index + 1 < len(card_headings) else len(section)
        )
        kind = _status_kind(section[heading.end() : card_end])
        if kind == "closed":
            closed += 1
        else:
            cards[kind].append(heading.group(1).strip())
    label = re.sub(r"^(?:>\s*)?##\s+", "", active.group(0)).strip()
    return label, cards, closed


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 1:
        return "…"
    return value[: limit - 1].rstrip() + "…"


def _bounded_lines(
    *,
    branch: str,
    board: str,
    next_selection: str,
    dirty: str,
    optional: list[str],
    max_chars: int,
) -> tuple[str, set[str]]:
    """Render decision-critical fields first and spend only spare space on details."""

    original_values = {
        "branch": branch,
        "board": board,
        "next": next_selection,
        "dirty": dirty,
    }
    values = {
        "branch": _clip(branch, 80),
        "board": _clip(board, 220),
        "next": _clip(next_selection, 300),
        "dirty": _clip(dirty, 800),
    }
    clipped = {key for key, value in values.items() if value != original_values[key]}
    compact = max_chars < 512

    def essentials() -> list[str]:
        if compact:
            return [
                "Docket snapshot",
                f"branch: {values['branch']}",
                f"board: {values['board']}",
                f"next: {values['next']}",
                f"dirty: {values['dirty']}",
                "routing: roadmap/spec/context",
                "authority: TODO/spec/live",
            ]
        return [
            "Docket development snapshot (bounded)",
            f"branch: {values['branch']}",
            f"board: {values['board']}",
            f"next selection: {values['next']}",
            f"dirty: {values['dirty']}",
            "routing: skills docket-roadmap | docket-spec-work | docket-context-runtime",
            "authority: TODO current board | owning spec | live path",
        ]

    output = "\n".join(essentials())
    while len(output) > max_chars:
        longest = max(values, key=lambda key: len(values[key]))
        current = values[longest]
        if len(current) <= 1:
            break
        overflow = len(output) - max_chars
        values[longest] = _clip(current, max(1, len(current) - overflow))
        clipped.add(longest)
        output = "\n".join(essentials())

    core = essentials()
    prefix, suffix = core[:3], core[3:]
    selected: list[str] = []
    skipped = False
    for detail in optional:
        candidate = _clip(detail, 320)
        rendered = "\n".join([*prefix, *selected, candidate, *suffix])
        if len(rendered) <= max_chars:
            selected.append(candidate)
        else:
            skipped = True
    if skipped:
        marker = "details: optional board entries clipped"
        rendered = "\n".join([*prefix, *selected, marker, *suffix])
        if len(rendered) <= max_chars:
            selected.append(marker)
    return "\n".join([*prefix, *selected, *suffix]), clipped


def snapshot(root: Path, max_files: int, max_chars: int) -> str:
    branch = _git(root, "branch", "--show-current") or "detached/unknown"
    git_status = _git(root, "status", "--short")
    dirty = [line.strip() for line in git_status.splitlines() if line.strip()] if git_status else []
    board, cards, closed = _board_summary(root)
    optional: list[str] = []
    labels = (
        ("in_progress", "in progress"),
        ("ready", "ready"),
        ("blocked", "blocked"),
        ("unknown", "status unknown"),
    )
    for kind, label in labels:
        if cards.get(kind):
            optional.append(f"{label}: " + " | ".join(cards[kind][:4]))
    if not any(cards.values()):
        optional.append("open cards: none in current board section")
    if closed:
        optional.append(f"closed cards in section: {closed}")

    dirty_truncated = len(dirty) > max_files
    dirty_details_clipped = False
    if git_status is None:
        dirty_text = "unknown (git status unavailable)"
    elif dirty:
        shown = dirty[:max_files]
        dirty_text = " | ".join(shown)
        dirty_char_limit = 60 if max_chars < 512 else 760
        dirty_details_clipped = dirty_truncated or len(dirty_text) > dirty_char_limit
        if dirty_details_clipped:
            reason = f"--max-files={max_files}" if dirty_truncated else "details clipped"
            dirty_text = f"incomplete ({len(dirty)} changed paths; {reason})"
    else:
        dirty_text = "clean"

    if git_status is None:
        next_selection = "resolve git status before claim or parallel work"
    elif dirty_details_clipped:
        next_selection = "expand full dirty status before claim or parallel work"
    elif cards.get("in_progress"):
        next_selection = f"resume {cards['in_progress'][0]}"
    elif cards.get("ready"):
        next_selection = f"inspect {cards['ready'][0]} dependencies/contention before claim"
    else:
        next_selection = "no ready card; run bounded triage/measurement before scheduling"

    output, clipped = _bounded_lines(
        branch=branch,
        board=board,
        next_selection=next_selection,
        dirty=dirty_text,
        optional=optional,
        max_chars=max_chars,
    )
    if "dirty" in clipped and git_status is not None and not dirty_details_clipped:
        next_selection = "expand full dirty status before claim or parallel work"
        output, _ = _bounded_lines(
            branch=branch,
            board=board,
            next_selection=next_selection,
            dirty=dirty_text,
            optional=optional,
            max_chars=max_chars,
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--max-files", type=int, default=12)
    parser.add_argument("--max-chars", type=int, default=1800)
    parser.add_argument("--hook", action="store_true", help="Compatibility flag for SessionStart")
    args = parser.parse_args()
    root = args.root.resolve() if args.root is not None else _default_root()
    print(snapshot(root, max(1, args.max_files), max(256, args.max_chars)))


if __name__ == "__main__":
    main()
