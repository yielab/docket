#!/usr/bin/env python3
"""Archive closed sections of a Markdown board verbatim into another file, with a hash manifest.

    split_board.py archive SOURCE DEST --level 2 --select 'REGEX' [--manifest PATH]
    split_board.py check MANIFEST

A section runs from its heading line (``##`` at level 2, ``###`` at level 3) to the next heading of
the same or a higher level. Matching sections are removed from SOURCE in place and appended to DEST
in their original order, byte for byte. The manifest records each section's heading, byte length
and SHA-256 so ``check`` can prove every archived section is present in DEST and absent from SOURCE.
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
    return 0


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
    return 1 if failures else 0


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
    args = ap.parse_args()
    if args.cmd == "archive":
        return archive(args.source, args.dest, args.level, args.select, args.manifest)
    return check(args.manifest)


if __name__ == "__main__":
    sys.exit(main())
