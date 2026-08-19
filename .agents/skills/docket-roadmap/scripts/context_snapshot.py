#!/usr/bin/env python3
"""Emit a bounded, deterministic Docket development context snapshot."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=False, capture_output=True, text=True, timeout=3
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _status_kind(body: str) -> str:
    match = re.search(r"^\*\*Status:\*\*\s*([^·\n]+)", body, flags=re.MULTILINE)
    if match is None:
        return "unknown"
    status = match.group(1).strip().upper()
    if status.startswith(("DONE", "COMPLETE", "CLOSED")):
        return "closed"
    if status.startswith("IN PROGRESS"):
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
    headings = list(re.finditer(r"^## (?:▶|☑) .+$", text, flags=re.MULTILINE))
    if not headings:
        return "no active/clear heading found", {}, 0
    active = next(
        (
            match
            for match in headings
            if "▶" in match.group(0)
            and re.search(r"\b(ACTIVE|IN PROGRESS)\b", match.group(0), flags=re.IGNORECASE)
        ),
        next(
            (
                match
                for match in headings
                if "☑" in match.group(0) and "BOARD CLEAR" in match.group(0).upper()
            ),
            headings[0],
        ),
    )
    end = text.find("\n## ", active.end())
    section = text[active.end() : end if end >= 0 else len(text)]
    headings = list(re.finditer(r"^### (.+)$", section, flags=re.MULTILINE))
    cards: dict[str, list[str]] = {
        "in_progress": [],
        "ready": [],
        "blocked": [],
        "unknown": [],
    }
    closed = 0
    for index, heading in enumerate(headings):
        card_end = headings[index + 1].start() if index + 1 < len(headings) else len(section)
        kind = _status_kind(section[heading.end() : card_end])
        if kind == "closed":
            closed += 1
        else:
            cards[kind].append(heading.group(1).strip())
    return active.group(0).removeprefix("## ").strip(), cards, closed


def snapshot(root: Path, max_files: int, max_chars: int) -> str:
    branch = _git(root, "branch", "--show-current") or "detached/unknown"
    dirty = _git(root, "status", "--short").splitlines()
    board, cards, closed = _board_summary(root)
    lines = [
        "Docket development snapshot (bounded; inspect sources only as needed)",
        f"branch: {branch}",
        f"board: {board}",
    ]
    labels = (
        ("in_progress", "in progress"),
        ("ready", "ready"),
        ("blocked", "blocked"),
        ("unknown", "status unknown"),
    )
    for kind, label in labels:
        if cards.get(kind):
            lines.append(f"{label}: " + " | ".join(cards[kind][:4]))
    if not any(cards.values()):
        lines.append("open cards: none in current board section")
    if closed:
        lines.append(f"closed cards in section: {closed}")
    if cards.get("in_progress"):
        lines.append(f"next selection: resume {cards['in_progress'][0]}")
    elif cards.get("ready"):
        lines.append(
            f"next selection: inspect {cards['ready'][0]} dependencies/contention before claim"
        )
    else:
        lines.append(
            "next selection: no ready card; run bounded triage/measurement before scheduling"
        )
    if dirty:
        shown = dirty[:max_files]
        suffix = f" (+{len(dirty) - len(shown)} more)" if len(dirty) > len(shown) else ""
        lines.append("dirty: " + " | ".join(shown) + suffix)
    else:
        lines.append("dirty: clean")
    lines.extend(
        [
            "routing: roadmap->$docket-roadmap; behavior->$docket-spec-work; "
            "context/loop/session/MCP->$docket-context-runtime",
            "authority: TODO active card; owning spec; live-path tests/code; ROADMAP named decisions",
        ]
    )
    output = "\n".join(lines)
    if len(output) > max_chars:
        output = output[: max_chars - 24].rstrip() + "\n[context snapshot clipped]"
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--max-files", type=int, default=12)
    parser.add_argument("--max-chars", type=int, default=1800)
    parser.add_argument("--hook", action="store_true", help="Compatibility flag for SessionStart")
    args = parser.parse_args()
    print(snapshot(args.root.resolve(), max(1, args.max_files), max(256, args.max_chars)))


if __name__ == "__main__":
    main()
