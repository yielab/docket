#!/usr/bin/env python3
"""Archive closed sections of a Markdown board verbatim into another file, with a hash manifest.

    split_board.py archive SOURCE DEST --level 2 --select 'REGEX' [--manifest PATH]
    split_board.py check MANIFEST
    split_board.py index MANIFEST [--write]

A section runs from its heading line to the next heading of the same or a higher level. Matching
sections move from SOURCE to DEST byte for byte; the manifest records heading, length and SHA-256 so
``check`` proves each is in DEST and gone from SOURCE. The README beside the manifest holds an index
generated from it between two markers: ``archive`` rewrites it and ``check`` fails when it is stale.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


def _heading_level(line: str) -> int:
    m = re.match(r"^(#{1,6}) ", line)
    return len(m.group(1)) if m else 0


def split_sections(text: str, level: int) -> list[tuple[str | None, str]]:
    """Return (heading_text_or_None, verbatim_chunk) pairs covering the whole file."""
    lines = text.splitlines(keepends=True)
    chunks: list[tuple[str | None, str]] = []
    current_heading: str | None = None
    buf: list[str] = []
    for line in lines:
        lvl = _heading_level(line)
        if lvl and lvl <= level:
            if buf:
                chunks.append((current_heading, "".join(buf)))
            buf = [line]
            current_heading = line.rstrip("\n")[lvl + 1 :] if lvl == level else None
        else:
            buf.append(line)
    if buf:
        chunks.append((current_heading, "".join(buf)))
    return chunks


INDEX_BEGIN = "<!-- archive-index:begin -->"
INDEX_END = "<!-- archive-index:end -->"
_HOLDS = {
    "todo-waves.md": "Closed board sections: waves, phase boards and registers",
    "roadmap-phases.md": "Completed-initiative and phase records",
    "roadmap-changelog.md": "The roadmap decision changelog (new entries go under its live heading)",
}


def render_index(entries: list[dict[str, object]]) -> str:
    """The generated block: per-file counts, then sections by date (newest first), then undated."""

    def cell(text: str) -> str:
        return text.replace("|", "\\|")

    counts: dict[str, int] = {}
    dated: list[tuple[str, dict[str, object]]] = []
    undated: list[dict[str, object]] = []
    for e in entries:
        name = Path(str(e["dest"])).name
        counts[name] = counts.get(name, 0) + 1
        m = re.search(r"\d{4}-\d{2}-\d{2}", str(e["heading"]))
        if m:
            dated.append((m.group(0), e))
        else:
            undated.append(e)
    dated.sort(key=lambda pair: pair[0], reverse=True)
    out = ["| File | Holds |", "|---|---|"]
    for name, count in counts.items():
        what = _HOLDS.get(name, "archived sections")
        out.append(f"| [{name}]({name}) | {what} ({count} archived) |")
    out.append("| [handoffs/](handoffs/) | Superseded coordinator handoff packets |")
    out += ["", "## Index by date (newest first)", "", "| Date | Section | File | Bytes |"]
    out.append("|---|---|---|---|")
    for date, e in dated:
        name = Path(str(e["dest"])).name
        out.append(f"| {date} | {cell(str(e['heading']))} | `{name}` | {int(e['bytes']):,} |")
    out += ["", "## Undated sections", "", "| Section | File | Bytes |", "|---|---|---|"]
    for e in undated:
        name = Path(str(e["dest"])).name
        out.append(f"| {cell(str(e['heading']))} | `{name}` | {int(e['bytes']):,} |")
    return "\n".join(out) + "\n"


def index(manifest_path: Path, write: bool) -> int:
    """Compare (or with *write*, replace) the README's marked block against the manifest."""
    readme = manifest_path.parent / "README.md"
    if not readme.exists():
        return 0
    text = readme.read_text(encoding="utf-8")
    if INDEX_BEGIN not in text or INDEX_END not in text:
        print(f"{readme}: index markers missing")
        return 1
    head, rest = text.split(INDEX_BEGIN, 1)
    _, tail = rest.split(INDEX_END, 1)
    entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    fresh = f"{head}{INDEX_BEGIN}\n{render_index(entries)}{INDEX_END}{tail}"
    if fresh == text:
        print(f"{readme}: index current ({len(entries)} sections)")
        return 0
    if write:
        readme.write_text(fresh, encoding="utf-8")
        print(f"{readme}: index rewritten ({len(entries)} sections)")
        return 0
    print(f"{readme}: index STALE; run split_board.py index {manifest_path} --write")
    return 1


def archive(source: Path, dest: Path, level: int, select: str, manifest_path: Path) -> int:
    pattern = re.compile(select)
    text = source.read_text(encoding="utf-8")
    chunks = split_sections(text, level)
    kept: list[str] = []
    moved: list[tuple[str, str]] = []
    for heading, chunk in chunks:
        if heading is not None and pattern.search(heading):
            moved.append((heading, chunk))
        else:
            kept.append(chunk)
    if not moved:
        print(f"no level-{level} section in {source} matches {select!r}")
        return 1

    manifest: list[dict[str, object]] = []
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = dest.read_text(encoding="utf-8") if dest.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    with dest.open("w", encoding="utf-8") as fh:
        fh.write(existing)
        for heading, chunk in moved:
            fh.write(chunk)
            manifest.append(
                {
                    "source": str(source),
                    "dest": str(dest),
                    "level": level,
                    "heading": heading,
                    "bytes": len(chunk.encode("utf-8")),
                    "sha256": hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                }
            )
    source.write_text("".join(kept), encoding="utf-8")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for heading, chunk in moved:
        print(f"moved  {len(chunk.encode('utf-8')):>7} B  {heading[:80]}")
    print(f"{len(moved)} section(s) -> {dest}; manifest {manifest_path}")
    return index(manifest_path, write=True)


def check(manifest_path: Path) -> int:
    entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures = 0
    dest_cache: dict[str, bytes] = {}
    for e in entries:
        dest = Path(str(e["dest"]))
        data = dest_cache.setdefault(str(dest), dest.read_bytes() if dest.exists() else b"")
        marker = ("#" * int(e["level"]) + " " + str(e["heading"])).encode("utf-8")
        found = False
        start = data.find(marker)
        while start != -1 and not found:
            window = data[start : start + int(e["bytes"])]
            found = hashlib.sha256(window).hexdigest() == e["sha256"]
            start = data.find(marker, start + 1)
        src = Path(str(e["source"]))
        still_in_source = src.exists() and marker in src.read_bytes()
        status = "ok" if found and not still_in_source else "FAIL"
        if status == "FAIL":
            failures += 1
        print(
            f"{status:4} {str(e['heading'])[:80]}"
            + ("  (still in source)" if still_in_source else "")
            + ("" if found else "  (not verbatim in dest)")
        )
    print(f"{len(entries) - failures}/{len(entries)} archived sections verified")
    return 1 if failures or index(manifest_path, write=False) else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("archive")
    a.add_argument("source", type=Path)
    a.add_argument("dest", type=Path)
    a.add_argument("--level", type=int, default=2, choices=(2, 3))
    a.add_argument(
        "--select", required=True, help="regex applied to the heading text (after the #s)"
    )
    a.add_argument("--manifest", type=Path, default=Path("docs/cycles-ended/manifest.json"))
    c = sub.add_parser("check")
    c.add_argument("manifest", type=Path)
    i = sub.add_parser("index")
    i.add_argument("manifest", type=Path)
    i.add_argument("--write", action="store_true")
    args = ap.parse_args()
    if args.cmd == "archive":
        return archive(args.source, args.dest, args.level, args.select, args.manifest)
    if args.cmd == "index":
        return index(args.manifest, args.write)
    return check(args.manifest)


if __name__ == "__main__":
    sys.exit(main())
