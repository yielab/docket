"""Write tests/fixtures/documents/bomb.pdf: a few KB of PDF that needs several GB to read.

Every page has its own content stream, deflated twice, that inflates to 70 MB of blanks after a
line of text. Each stream is under pypdf's own decompression cap, so the reader accepts it, and
pypdf keeps every decoded stream while it reads the next page: reading all the pages holds
PAGES x 70 MB. A reader that is not memory-limited grows until the machine pushes back.

    python scripts/maint/make_pdf_bomb.py [out.pdf]
"""

from __future__ import annotations

import sys
import zlib
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "tests/fixtures/documents/bomb.pdf"
PAGES = 40
INFLATED_BYTES = 70_000_000
FONT = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"


def content() -> bytes:
    """One page's content stream, deflated twice; a line of text, then INFLATED_BYTES of blanks."""
    raw = b"BT /F1 12 Tf (x) Tj ET" + b" " * INFLATED_BYTES
    return zlib.compress(zlib.compress(raw, 9), 9)


def build() -> bytes:
    stream = content()
    kids = b" ".join(b"%d 0 R" % (3 + 2 * i) for i in range(PAGES))
    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, PAGES),
    ]
    for i in range(PAGES):
        bodies.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] "
            b"/Resources << /Font << /F1 %s >> >> /Contents %d 0 R >>" % (FONT, 4 + 2 * i)
        )
        bodies.append(
            b"<< /Filter [/FlateDecode /FlateDecode] /Length %d >>\nstream\n" % len(stream)
            + stream
            + b"\nendstream"
        )
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(bodies, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(bodies) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(bodies) + 1,
        xref,
    )
    return bytes(out)


def main(argv: list[str]) -> int:
    target = Path(argv[0]) if argv else DEFAULT_OUT
    target.write_bytes(build())
    print(f"wrote {target} ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
