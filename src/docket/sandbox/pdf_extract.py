"""The PDF text extractor: ``python -I extract.py in.pdf`` prints each page's text to stdout.

It runs only inside the jail, as a copy of this file beside ``in.pdf`` (the copy is why it imports
nothing of docket: a development checkout's source tree lies outside the jail's read roots, while
the interpreter and ``pypdf`` lie under ``sys.prefix``). It imports the standard library and
``pypdf`` alone. It lowers its own address-space (best effort: macOS does not enforce it) and CPU limits
before it opens the document, so a document that inflates past memory fails here and takes nothing
else down. A failure is exit 1
with one line on stderr; the caller treats any non-zero exit as a refusal and drops the output.
"""

from __future__ import annotations

import contextlib
import logging
import os
import resource
import sys

MEMORY_BYTES = 1 << 30
CPU_SECONDS = 60
_ERROR_CHARS = 200


def _limit(which: int, value: int) -> None:
    """Lower *which* to *value* (soft and hard, so the parser cannot raise it again)."""
    _, hard = resource.getrlimit(which)
    cap = value if hard == resource.RLIM_INFINITY else min(value, hard)
    resource.setrlimit(which, (cap, cap))


def _apply_limits() -> str | None:
    """Lower both limits; the reason the CPU limit could not be set, else ``None``. The address-space
    limit is best effort: macOS does not enforce ``RLIMIT_AS`` and ``setrlimit`` may refuse it, and
    there memory is bounded only by the caller's deadline (security-gates.spec.md, fetch)."""
    with contextlib.suppress(ValueError, OSError):
        _limit(resource.RLIMIT_AS, MEMORY_BYTES)
    try:
        _limit(resource.RLIMIT_CPU, CPU_SECONDS)
    except (ValueError, OSError) as ex:
        return f"cannot bound the reader's CPU time: {ex}"
    return None


def _fail(reason: str) -> int:
    os.write(2, (reason.splitlines()[0][:_ERROR_CHARS] + "\n").encode("utf-8", "replace"))
    return 1


def _extract(path: str) -> int:
    import pypdf  # imported after the limits, so even its import runs under them

    logging.disable(logging.CRITICAL)  # pypdf warns about sloppy files; the exit status says more
    reader = pypdf.PdfReader(path)
    if reader.is_encrypted and not reader.decrypt(""):
        return _fail("the PDF is encrypted and needs a password")
    out = sys.stdout.buffer
    for page in reader.pages:
        out.write(page.extract_text().encode("utf-8", "replace") + b"\n")
    out.flush()
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        return _fail("usage: extract.py in.pdf")
    unbounded = _apply_limits()
    if unbounded is not None:
        return _fail(unbounded)
    try:
        return _extract(argv[0])
    except MemoryError:
        return _fail("the PDF needs more memory than the reader may use")
    except RecursionError:
        return _fail("the PDF is nested too deeply to read")
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
