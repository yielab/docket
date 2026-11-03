"""A PDF's text, read by `pdftotext` inside the jail and never in docket's own process.

A hostile PDF is parsed by a hostile-input parser, so the parse runs in the turn's jail: the
bytes go to a fresh private directory that is the jail's only root, the network is off, the
environment holds the temp variables and `PATH` and no credential, and the run is killed at the
fetch deadline. It fails closed (`security-gates.spec.md`, `fetch`): without isolation, a usable
backend or the extractor there is a refusal naming the fix, never an unjailed run. The process
mechanics are `platform/fetch.py`'s `run_jailed`; this module decides whether to run and what the
outcome means.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

from docket.kernel import clock as _clock
from docket.kernel.errors import Refused
from docket.kernel.home import current_home
from docket.kernel.ports import jail as _jail
from docket.kernel.tool_outcome import ToolOutcome, bounded_text
from docket.platform import fetch as _fetch

EXTRACTOR = "pdftotext"
_INPUT = "in.pdf"
_ARGS = ("-enc", "UTF-8", "-nopgbrk", "-q", "--", _INPUT, "-")
# The most the extractor's stdout is read for; the tool's own output cap then applies to it.
_MAX_TEXT_BYTES = 2_000_000
_ERROR_CHARS = 200
_SAFE_PATH = "/usr/bin:/bin"
_BACKENDS = ("landlock", "seatbelt", "docker")
_NEEDS_JAIL = (
    "reading a PDF needs the jail: turn isolation on with 'docket setup sandbox on' "
    "(Landlock, Seatbelt or Docker); fetch never parses a PDF outside it"
)
_NO_TEXT = "[the PDF holds no text; a scanned page needs OCR, which fetch does not do]"

Runner = Callable[[_fetch.JailedRun], _fetch.Ran]
Workdir = Callable[[bytes, tuple[Path, ...], Path | None], AbstractContextManager[Path]]


@contextmanager
def fresh_workdir(body: bytes, roots: tuple[Path, ...], cache_dir: Path | None) -> Iterator[Path]:
    """A new 0700 directory under the jail's temp dir holding *body* as `in.pdf`, removed on exit."""
    if not roots and cache_dir is None:
        raise Refused("the turn has no root to place the jail's temp directory under")
    base = _jail.jail_tmp_dir(roots, cache_dir)
    root = Path(tempfile.mkdtemp(prefix="pdf-", dir=base)).resolve()
    try:
        fd = os.open(root / _INPUT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _refused(why: str) -> ToolOutcome:
    return ToolOutcome(False, error=why, refusal="fetch_not_allowed")


def _first_line(stderr: bytes) -> str:
    text = stderr.decode("utf-8", errors="replace").strip()
    return text.splitlines()[0][:_ERROR_CHARS] if text else ""


def _not_runnable(found: str | None, backend: str, line: str) -> ToolOutcome:
    """The refusal for an extractor the jail could not start: the fix depends on where it was."""
    if backend == "docker":
        image = current_home().sandbox_docker_image
        return _refused(
            f"the docker image {image!r} has no {EXTRACTOR}; set DOCKET_SANDBOX_IMAGE to an image "
            "that has poppler, or use Landlock or Seatbelt"
        )
    prefix = Path(found).parent.parent if found else Path("<prefix>")
    return _refused(
        f"the jail cannot execute {EXTRACTOR} ({line}); it lies outside the jail's default read "
        f"roots, so run: docket setup sandbox read add {prefix}"
    )


def _outcome(ran: _fetch.Ran, found: str | None, backend: str) -> ToolOutcome:
    if ran.timed_out:
        return _refused(
            "timed out reading the PDF's text; the extractor was killed at the deadline"
        )
    line = _first_line(ran.stderr)
    if not ran.cut and ran.returncode != 0:
        if ran.returncode in (126, 127) and (backend == "docker" or "ermission denied" in line):
            return _not_runnable(found, backend, line)
        if ran.returncode == 125:
            return _refused(f"the jail refused to run the extractor: {line or 'no reason given'}")
        return _refused(f"{EXTRACTOR} exited {ran.returncode}" + (f": {line}" if line else ""))
    text = ran.stdout.decode("utf-8", errors="replace")
    if not text.strip():
        return ToolOutcome(True, content=_NO_TEXT)
    if ran.cut:
        text += f"\n\n[truncated: the extractor's output exceeded {_MAX_TEXT_BYTES} bytes]"
    return ToolOutcome(True, content=bounded_text(text))


def pdf_text(
    body: bytes,
    *,
    sandbox: str,
    roots: tuple[Path, ...],
    cache_dir: Path | None,
    read_only: tuple[Path, ...],
    deadline: float,
    run: Runner = _fetch.run_jailed,
    workdir: Workdir = fresh_workdir,
    which: Callable[[str], str | None] = shutil.which,
) -> ToolOutcome:
    """The text of the PDF *body*, or a refusal (``fetch_not_allowed``) naming its fix. *deadline*
    is the fetch call's, in monotonic seconds. *read_only* is the operator's grants; the jail
    reads nothing else of the host beyond its default roots and writes only its own directory."""
    try:
        if sandbox != "auto":
            return _refused(_NEEDS_JAIL)
        backend = _jail.sandbox_availability().backend
        if backend not in _BACKENDS:
            return _refused(_NEEDS_JAIL)
        seconds = deadline - _clock.monotonic()
        if seconds <= 0:
            return _refused("timed out before the PDF's text could be read")
        # A docker image carries its own extractor; the host's path means nothing there.
        found = EXTRACTOR if backend == "docker" else which(EXTRACTOR)
        if found is None:
            return _refused(
                f"{EXTRACTOR} is not on PATH; install poppler (apt install poppler-utils, "
                "brew install poppler) to read a PDF"
            )
        with workdir(body, roots, cache_dir) as root:
            # Only the docker CLI is found through PATH; the other backends run an absolute path.
            path = os.environ.get("PATH", _SAFE_PATH) if backend == "docker" else _SAFE_PATH
            env = {"PATH": path, **_jail.tmp_environment(root)}
            job = _fetch.JailedRun(
                backend=backend,
                root=root,
                command=(found, *_ARGS),
                env=env,
                read_only=read_only,
                seconds=seconds,
                max_output=_MAX_TEXT_BYTES,
            )
            ran = run(job)
        return _outcome(ran, found, backend)
    except Exception as ex:  # fail closed: whatever went wrong, nothing ran outside the jail
        return _refused(
            f"could not read the PDF in the jail ({type(ex).__name__}: {str(ex)[:_ERROR_CHARS]})"
        )
