#!/usr/bin/env python3
"""Print exactly one bounded TODO card without loading the planning corpus."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_CARD_ID = re.compile(r"[A-Z0-9]+(?:-[A-Za-z0-9]+)+")


def _git_root(cwd: Path) -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return cwd.resolve()
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else cwd.resolve()


def extract_card(board: str, card_id: str) -> str:
    """Return one complete H3 card, stopping before the next H2/H3 heading."""

    if _CARD_ID.fullmatch(card_id) is None:
        raise ValueError(f"invalid card id: {card_id!r}")
    heading = re.compile(rf"^### {re.escape(card_id)}(?:\s+—|\s+-)\s+.+$", re.MULTILINE)
    matches = list(heading.finditer(board))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one card with id {card_id}; found {len(matches)}")
    start = matches[0].start()
    next_heading = re.search(r"^##(?:#)?\s+", board[matches[0].end() :], re.MULTILINE)
    end = matches[0].end() + next_heading.start() if next_heading is not None else len(board)
    return board[start:end].rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print one exact TODO.md card and fail rather than silently truncate it."
    )
    parser.add_argument("card_id")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--max-bytes", type=int, default=12_000)
    args = parser.parse_args()

    root = args.root.resolve() if args.root is not None else _git_root(Path.cwd())
    board_path = root / "TODO.md"
    try:
        board = board_path.read_text(encoding="utf-8")
        packet = extract_card(board, args.card_id)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"card_packet: {exc}", file=sys.stderr)
        return 2

    max_bytes = max(256, args.max_bytes)
    size = len(packet.encode("utf-8"))
    if size > max_bytes:
        print(
            f"card_packet: {args.card_id} is {size} bytes and exceeds "
            f"--max-bytes={max_bytes}; card was not truncated",
            file=sys.stderr,
        )
        return 2
    sys.stdout.write(packet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
