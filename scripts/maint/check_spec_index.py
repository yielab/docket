#!/usr/bin/env python3
"""Reconcile specs/README.md's status table and file tree against the specs on disk.

specs/README.md declares itself a mirror of every spec's own Version/Status header, but
nothing re-derives that mirror from the specs themselves, so it can drift silently while
scripts/validate-specs.sh (which checks each spec's own required sections, never the index)
keeps passing. This script is that missing derivation, run standalone or as a test guard.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SPECS = REPO / "specs"
INDEX = SPECS / "README.md"

VERSION_RE = re.compile(r"\*\*Version\*\*:?\s*([^\s]+)")
STATUS_RE = re.compile(r"\*\*Status\*\*:?\s*(.+)")
TREE_FENCE_RE = re.compile(r"```text\n(.*?)\n```", re.DOTALL)
TABLE_ROW_RE = re.compile(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|")

# Words capitalized verbatim by the table/tree naming convention; every other hyphen
# segment is title-cased. Extend this set, never special-case a single spec name.
ACRONYMS = {"cli", "api", "mcp", "json"}

# Table display names that cannot be produced by the mechanical stem transform below.
NAME_OVERRIDES = {"docket-meta": "docket-meta schema"}
REVERSE_OVERRIDES = {v: k for k, v in NAME_OVERRIDES.items()}


@dataclass(frozen=True)
class SpecFile:
    rel_path: str  # POSIX path relative to specs/, e.g. "functional/agent-loop.spec.md"
    stem: str  # filename without ".spec.md", e.g. "agent-loop"
    version: str | None
    status: str | None


@dataclass(frozen=True)
class TableRow:
    name: str
    version: str
    status: str


@dataclass(frozen=True)
class Disagreement:
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.detail}"


def stem_to_display(stem: str) -> str:
    if stem in NAME_OVERRIDES:
        return NAME_OVERRIDES[stem]
    return " ".join(w.upper() if w in ACRONYMS else w.capitalize() for w in stem.split("-"))


def display_to_stem(display: str) -> str:
    if display in REVERSE_OVERRIDES:
        return REVERSE_OVERRIDES[display]
    return "-".join(w.lower() for w in display.split(" "))


def status_category(status: str) -> str:
    """Leading word of a Status value: the only fair comparison against a paraphrase."""
    first = status.strip().lstrip("*").split()[0] if status.strip() else ""
    return first.strip(".,;:()").rstrip("*")


def find_spec_files() -> list[SpecFile]:
    out = []
    for path in sorted(SPECS.rglob("*.spec.md")):
        text = path.read_text(encoding="utf-8")
        version_match = VERSION_RE.search(text)
        status_match = STATUS_RE.search(text)
        rel = path.relative_to(SPECS).as_posix()
        stem = path.name.removesuffix(".spec.md")
        out.append(
            SpecFile(
                rel_path=rel,
                stem=stem,
                version=version_match.group(1) if version_match else None,
                status=status_match.group(1) if status_match else None,
            )
        )
    return out


def find_non_spec_docs() -> set[str]:
    """Stems of specs/**/*.md files that are not *.spec.md (e.g. test-framework.md)."""
    stems = set()
    for path in sorted(SPECS.rglob("*.md")):
        if path.name == "README.md" or path.name.endswith(".spec.md"):
            continue
        stems.add(path.stem)
    return stems


def parse_tree(index_text: str) -> str:
    match = TREE_FENCE_RE.search(index_text)
    return match.group(1) if match else ""


def parse_table(index_text: str) -> list[TableRow]:
    rows = []
    in_table = False
    for line in index_text.splitlines():
        if line.startswith("| Specification "):
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            break
        if set(line.replace("|", "").strip()) <= {"-", " "}:
            continue
        match = TABLE_ROW_RE.match(line)
        if match:
            rows.append(
                TableRow(name=match.group(1), version=match.group(2), status=match.group(3))
            )
    return rows


def check(index_text: str) -> list[Disagreement]:
    findings: list[Disagreement] = []
    specs = find_spec_files()
    non_spec_stems = find_non_spec_docs()
    tree = parse_tree(index_text)
    rows = parse_table(index_text)
    rows_by_name = {row.name: row for row in rows}

    for spec in specs:
        display = stem_to_display(spec.stem)
        row = rows_by_name.get(display)
        if row is None:
            findings.append(
                Disagreement("missing_row", f"{spec.rel_path} has no row ({display!r})")
            )
        else:
            if spec.version is not None and row.version != spec.version:
                findings.append(
                    Disagreement(
                        "version_mismatch",
                        f"{display}: table says {row.version}, spec header says {spec.version}",
                    )
                )
            if spec.status is not None:
                row_cat = status_category(row.status)
                spec_cat = status_category(spec.status)
                if row_cat != spec_cat:
                    findings.append(
                        Disagreement(
                            "status_mismatch",
                            f"{display}: table says {row_cat!r}, spec header says {spec_cat!r}",
                        )
                    )
        if spec.rel_path.split("/")[-1] not in tree:
            findings.append(Disagreement("missing_from_tree", spec.rel_path))

    spec_stems = {s.stem for s in specs}
    for row in rows:
        stem = display_to_stem(row.name)
        if stem in spec_stems:
            continue
        if stem in non_spec_stems:
            continue
        findings.append(Disagreement("stale_row", f"{row.name!r} names no file on disk"))

    return findings


def indexed_specs() -> dict[str, str]:
    """Every spec the public index must cover, keyed by its expected table label.

    Lives here rather than in the test so that the agent lane, which is budgeted by a
    shrink-only line ratchet, does not pay for a naming convention this script already owns.
    """
    discovered = {
        stem_to_display(path.name.removesuffix(".spec.md")): path.relative_to(SPECS).as_posix()
        for path in sorted(SPECS.rglob("*.spec.md"))
    }
    # Both carry real Version/Status headers but are plain .md, not .spec.md, by design.
    discovered["Test Framework"] = "test-framework.md"
    discovered["User Stories"] = "acceptance/user-stories.md"
    return discovered


def format_report(findings: list[Disagreement]) -> str:
    if not findings:
        return "specs/README.md agrees with every specs/**/*.spec.md header."
    lines = [f"{len(findings)} disagreement(s) between specs/README.md and the specs on disk:"]
    lines.extend(f"  - {f}" for f in findings)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="exit 1 if any disagreement is found")
    args = ap.parse_args(argv)

    findings = check(INDEX.read_text(encoding="utf-8"))
    print(format_report(findings))
    return 1 if (args.check and findings) else 0


if __name__ == "__main__":
    sys.exit(main())
