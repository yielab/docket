#!/usr/bin/env python3
"""Repack one wheel with Docket's checksum-pinned canonical Deflate compressor."""

from __future__ import annotations

import argparse
import os
import subprocess
import zipfile
from pathlib import Path
from typing import Any

COMPRESSION_LEVEL = 6


class CanonicalCompressor:
    """Buffer one member, then compress it with the pinned zlib-ng executable."""

    def __init__(self, executable: Path) -> None:
        self._executable = executable
        self._data = bytearray()

    def compress(self, data: bytes) -> bytes:
        self._data.extend(data)
        return b""

    def flush(self) -> bytes:
        result = subprocess.run(
            [
                str(self._executable),
                "-c",
                "-w",
                "-15",
                "-r",
                str(len(self._data) + 1),
                "-t",
                str(len(self._data) + 1024),
                f"-{COMPRESSION_LEVEL}",
            ],
            input=bytes(self._data),
            capture_output=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"canonical compressor failed: {detail}")
        return result.stdout


def _copy_info(source: zipfile.ZipInfo) -> zipfile.ZipInfo:
    copied = zipfile.ZipInfo(source.filename, source.date_time)
    copied.compress_type = source.compress_type
    copied.comment = source.comment
    copied.extra = source.extra
    copied.internal_attr = source.internal_attr
    copied.external_attr = source.external_attr
    copied.create_system = source.create_system
    copied.create_version = source.create_version
    copied.extract_version = source.extract_version
    copied.flag_bits = source.flag_bits
    return copied


def canonicalize(wheel: Path, compressor: Path) -> None:
    if not wheel.is_file():
        raise RuntimeError(f"wheel does not exist: {wheel}")
    if not compressor.is_file():
        raise RuntimeError(f"canonical compressor does not exist: {compressor}")

    with zipfile.ZipFile(wheel, "r") as incoming:
        archive_comment = incoming.comment
        entries = [(entry, incoming.read(entry.filename)) for entry in incoming.infolist()]

    original_factory = zipfile._get_compressor  # type: ignore[attr-defined]

    def factory(compress_type: int, compresslevel: int | None = None) -> Any:
        if compress_type == zipfile.ZIP_DEFLATED:
            return CanonicalCompressor(compressor)
        fallback = original_factory
        return fallback(compress_type, compresslevel)

    temporary = wheel.with_suffix(".canonical.whl")
    zipfile._get_compressor = factory  # type: ignore[attr-defined]
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=COMPRESSION_LEVEL,
            strict_timestamps=True,
        ) as outgoing:
            outgoing.comment = archive_comment
            for entry, data in entries:
                outgoing.writestr(
                    _copy_info(entry),
                    data,
                    compresslevel=COMPRESSION_LEVEL,
                )
    finally:
        zipfile._get_compressor = original_factory  # type: ignore[attr-defined]

    os.replace(temporary, wheel)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--compressor", required=True, type=Path)
    args = parser.parse_args()
    canonicalize(args.wheel, args.compressor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
