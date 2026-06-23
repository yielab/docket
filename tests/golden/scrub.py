#!/usr/bin/env python3
"""
Normalise volatile fields in docket output so golden files are deterministic.

Rules applied (in order):
  1. Absolute paths under SCRUB_HOME → <HOME>
  2. Absolute paths under /tmp → <TMP>
  3. ISO-8601 timestamps → <TIMESTAMP>
  4. Relative time strings ("3h ago", "2 days ago", "just now", etc.) → <RELATIVE_TIME>
  5. Date strings (YYYY-MM-DD) → <DATE>
  6. Duration values ("1m23s", "0.42s") → <DURATION>
  7. Lock/tmp filenames (*.tmp, *.lock, *.bak) → <TMPFILE>
  8. Agent session UUIDs / random hex strings (32+ hex chars) → <HEX_ID>

Usage:
    ./scrub.py [--home PATH] < raw_output > scrubbed_output
    ./scrub.py --home /tmp/fake-home < raw_output

SCRUB_HOME defaults to $DOCKET_FAKE_HOME env var, then $HOME.
"""

import re
import sys
import os
import argparse


ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mKHFJA-Z]|\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def build_rules(home: str) -> list[tuple[re.Pattern, str]]:
    return [
        # Home directory (must come before generic paths)
        (re.compile(re.escape(home)), "<HOME>"),
        # /tmp paths
        (re.compile(r"/tmp/[^\s\"']+"), "<TMP>"),
        # ISO-8601 datetime  2026-03-05T12:08:17-03:00 or Z
        (re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)"), "<TIMESTAMP>"),
        # Relative times: "3h ago", "2 days ago", "just now", "moments ago"
        (re.compile(r"\bjust now\b|\bmoments? ago\b"), "<RELATIVE_TIME>"),
        (re.compile(r"\b\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago\b"), "<RELATIVE_TIME>"),
        (re.compile(r"\b\d+[smhd]\s+ago\b"), "<RELATIVE_TIME>"),
        # Date-only  2026-03-05
        (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), "<DATE>"),
        # Durations  1m23s  0.42s  3.1ms
        (re.compile(r"\b\d+m\d+s\b|\b\d+(?:\.\d+)?(?:ms|s)\b"), "<DURATION>"),
        # Tmp/lock/bak filenames
        (re.compile(r"\S+\.(?:tmp|lock|bak)\b"), "<TMPFILE>"),
        # Long hex strings (32+ chars) — UUIDs, random ids
        (re.compile(r"\b[0-9a-f]{32,}\b"), "<HEX_ID>"),
    ]


def scrub(text: str, rules: list[tuple[re.Pattern, str]]) -> str:
    for pattern, replacement in rules:
        text = pattern.sub(replacement, text)
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrub volatile fields from docket output")
    parser.add_argument("--home", default=os.environ.get("DOCKET_FAKE_HOME", os.environ.get("HOME", "")))
    args = parser.parse_args()

    rules = build_rules(args.home)
    for line in sys.stdin:
        sys.stdout.write(scrub(strip_ansi(line), rules))


if __name__ == "__main__":
    main()
