"""``pdf_text``: a PDF's text is read by docket's own interpreter in the jail, and every other path refuses."""

from __future__ import annotations

import dataclasses
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from tests.support.fakes import FakeJail

from docket.hops.application import pdf_text as _pdf
from docket.kernel import clock as _clock
from docket.kernel.home import current_home, use_home
from docket.kernel.ports import SandboxAvailability
from docket.kernel.tool_outcome import ToolOutcome
from docket.platform import fetch as _fetch

SUBJECT = "docket.hops.application.pdf_text"

_ROOT = Path("/jail/root")
_GRANT = Path("/grants/brew")
_OWN = (sys.executable, "-I", "extract.py", "in.pdf")


class _Runner:
    """A runner that records what it was given and answers with *ran* (or raises *raises*)."""

    def __init__(self, ran: _fetch.Ran | None = None, raises: Exception | None = None) -> None:
        self.ran = ran or _fetch.Ran(0, b"Hola docket\n", b"")
        self.raises = raises
        self.runs: list[_fetch.JailedRun] = []

    def __call__(self, run: _fetch.JailedRun) -> _fetch.Ran:
        self.runs.append(run)
        if self.raises:
            raise self.raises
        return self.ran


class _Workdir:
    """A workdir that touches no disk and records whether it was opened and closed."""

    def __init__(self) -> None:
        self.opened = 0
        self.closed = 0
        self.bodies: list[bytes] = []

    @contextmanager
    def __call__(
        self, body: bytes, roots: tuple[Path, ...], cache_dir: Path | None
    ) -> Iterator[Path]:
        self.opened += 1
        self.bodies.append(body)
        try:
            yield _ROOT
        finally:
            self.closed += 1


def _backend(jail: FakeJail, backend: str, credentials: set[str] | None = None) -> FakeJail:
    jail.availability = SandboxAvailability(backend=backend, docker=backend == "docker")  # type: ignore[arg-type]
    jail.credentials = set(credentials or ())
    return jail


def _read(
    jail: FakeJail,
    runner: _Runner,
    *,
    workdir: _Workdir | None = None,
    sandbox: str = "auto",
    seconds: float = 10.0,
    body: bytes = b"%PDF-1.4",
) -> tuple[ToolOutcome, _Workdir]:
    spy = workdir or _Workdir()
    out = _pdf.pdf_text(
        body,
        sandbox=sandbox,  # type: ignore[arg-type]
        roots=(Path("/work"),),
        cache_dir=None,
        read_only=(_GRANT,),
        deadline=_clock.monotonic() + seconds,
        run=runner,
        workdir=spy,
    )
    return out, spy


class TestFailsClosed:
    @pytest.mark.parametrize(
        ("sandbox", "backend"), [("auto", "none"), ("off", "landlock"), ("off", "none")]
    )
    def test_no_jail_means_no_run_and_no_directory(
        self, fake_jail: FakeJail, sandbox: str, backend: str
    ) -> None:
        runner = _Runner()
        out, spy = _read(_backend(fake_jail, backend), runner, sandbox=sandbox)

        assert not out.ok
        assert out.refusal == "fetch_not_allowed"
        assert "reading a PDF needs the jail" in out.error
        assert runner.runs == []
        assert spy.opened == 0

    def test_a_backend_nobody_knows_is_not_run_either(self, fake_jail: FakeJail) -> None:
        runner = _Runner()
        out, _ = _read(_backend(fake_jail, "plan9"), runner)

        assert not out.ok
        assert runner.runs == []

    def test_a_runner_that_raises_is_a_refusal_and_the_directory_is_still_closed(
        self, fake_jail: FakeJail
    ) -> None:
        runner = _Runner(raises=RuntimeError("boom"))
        out, spy = _read(_backend(fake_jail, "landlock"), runner)

        assert not out.ok
        assert out.refusal == "fetch_not_allowed"
        assert "RuntimeError" in out.error
        assert (spy.opened, spy.closed) == (1, 1)

    def test_a_timeout_is_a_refusal_naming_the_deadline(self, fake_jail: FakeJail) -> None:
        runner = _Runner(_fetch.Ran(None, b"", b"", timed_out=True))
        out, spy = _read(_backend(fake_jail, "landlock"), runner)

        assert not out.ok
        assert "timed out" in out.error
        assert spy.closed == 1

    def test_a_deadline_already_past_never_starts_the_extractor(self, fake_jail: FakeJail) -> None:
        runner = _Runner()
        out, _ = _read(_backend(fake_jail, "landlock"), runner, seconds=-1.0)

        assert not out.ok
        assert "timed out" in out.error
        assert runner.runs == []


class TestTheExtractor:
    @pytest.mark.parametrize("backend", ["landlock", "seatbelt"])
    def test_docket_s_own_interpreter_runs_the_extractor_with_no_lookup(
        self, fake_jail: FakeJail, backend: str
    ) -> None:
        runner = _Runner()
        out, _ = _read(_backend(fake_jail, backend), runner)

        assert out.ok
        assert runner.runs[0].command == _OWN
        assert runner.runs[0].read_only == (_GRANT,)  # the operator's grants, none added

    def test_a_jail_that_cannot_start_the_interpreter_gives_its_reason_and_no_poppler_advice(
        self, fake_jail: FakeJail
    ) -> None:
        denied = _fetch.Ran(127, b"", b"jail: cannot run /x/python: Permission denied\n")
        out, _ = _read(_backend(fake_jail, "landlock"), _Runner(denied))

        assert not out.ok
        assert "Permission denied" in out.error
        assert "poppler" not in out.error and "read add" not in out.error

    def test_docker_runs_the_images_own_pdftotext(self, fake_jail: FakeJail) -> None:
        runner = _Runner()
        out, _ = _read(_backend(fake_jail, "docker"), runner)

        assert out.ok
        assert runner.runs[0].command == (
            "pdftotext", "-enc", "UTF-8", "-nopgbrk", "-q", "--", "in.pdf", "-",
        )  # fmt: skip

    def test_docker_without_it_names_the_image(self, fake_jail: FakeJail) -> None:
        runner = _Runner(_fetch.Ran(127, b"", b"exec: not found\n"))
        out, _ = _read(_backend(fake_jail, "docker"), runner)

        assert not out.ok
        assert current_home().sandbox_docker_image in out.error
        assert "pdftotext" in out.error

    def test_a_non_zero_exit_gives_the_first_line_of_stderr_bounded(
        self, fake_jail: FakeJail
    ) -> None:
        err = b"PdfReadError: " + b"x" * 1000 + b"\nsecond line\n"
        out, _ = _read(_backend(fake_jail, "landlock"), _Runner(_fetch.Ran(1, b"", err)))

        assert not out.ok
        assert out.error.startswith("the PDF reader exited 1: PdfReadError: ")
        assert "second line" not in out.error
        assert len(out.error) < 400


class TestWhatTheRunnerIsGiven:
    def test_one_root_no_network_the_operators_grants_and_no_credential_in_the_environment(
        self, fake_jail: FakeJail
    ) -> None:
        jail = _backend(fake_jail, "landlock", {"MY_PROVIDER_KEY"})
        runner = _Runner()
        _, spy = _read(jail, runner, body=b"%PDF-1.7 bytes")
        (run,) = runner.runs

        assert run.root == _ROOT
        assert run.network is False
        assert run.backend == "landlock"
        assert run.read_only == (_GRANT,)
        assert not set(run.env) & jail.credential_names()
        assert run.env["TMPDIR"] == str(_ROOT)
        assert run.command == _OWN
        assert spy.bodies == [b"%PDF-1.7 bytes"]
        assert (spy.opened, spy.closed) == (1, 1)

    def test_the_run_is_bounded_by_what_is_left_of_the_deadline(self, fake_jail: FakeJail) -> None:
        runner = _Runner()
        _read(_backend(fake_jail, "landlock"), runner, seconds=7.0)

        assert 0 < runner.runs[0].seconds <= 7.0


class TestTheText:
    def test_the_text_comes_back(self, fake_jail: FakeJail) -> None:
        out, _ = _read(_backend(fake_jail, "landlock"), _Runner())

        assert out.ok
        assert out.content == "Hola docket\n"

    def test_output_over_the_cap_announces_its_truncation(self, fake_jail: FakeJail) -> None:
        runner = _Runner(_fetch.Ran(0, ("palabra " * 100).encode(), b""))
        with use_home(dataclasses.replace(current_home(), tool_max_output_chars=100)):
            out, _ = _read(_backend(fake_jail, "landlock"), runner)

        assert out.ok
        assert "[truncated:" in out.content

    def test_an_extractor_cut_short_by_the_byte_bound_says_so(self, fake_jail: FakeJail) -> None:
        runner = _Runner(_fetch.Ran(0, b"cut here", b"", cut=True))
        out, _ = _read(_backend(fake_jail, "landlock"), runner)

        assert out.ok
        assert "cut here" in out.content
        assert "[truncated: the extractor's output exceeded" in out.content

    def test_a_pdf_with_no_text_layer_says_so(self, fake_jail: FakeJail) -> None:
        out, _ = _read(_backend(fake_jail, "landlock"), _Runner(_fetch.Ran(0, b"\n", b"")))

        assert out.ok
        assert "no text" in out.content
