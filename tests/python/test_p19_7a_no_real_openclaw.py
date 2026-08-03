"""The suite must never invoke the developer's real ``openclaw`` binary.

``edges/adapters/openclaw.py`` shells out to ``openclaw`` in several places
(``wire_channel``, ``add_agent``, the version and approval probes). Before the
autouse ``_shim_openclaw_on_path`` fixture existed, only tests that explicitly
requested ``fake_openclaw`` had a shim on PATH; every other test fell through
to whatever ``openclaw`` happened to be installed on the machine.

**This was measured, not theorised.** Wrapping the real binary in a logging
shim and running the full suite caught **17 real invocations**, five of which
wrote to the developer's actual ``~/.openclaw/openclaw.json`` -- Telegram
allowlist entries and ``agents add`` registrations. Four fake group bindings
from tests were found in that real config afterwards, and the daemon's own
``config-audit.jsonl`` recorded each write. The log grew *only* while the suite
ran (nothing across a four-minute idle window), which ruled out background
daemon activity.

The condition is **pre-existing** -- present at ``e9ef2cd``, before wave 11 --
and disappears entirely at P19-7b, which deletes every ``openclaw`` shell-out.
This guard exists so it cannot come back in the meantime, and so that whoever
lands P19-7b can delete this file knowing exactly what it was protecting.

Note what this guard does **not** claim: it proves the resolved binary is a
shim, not that no subprocess is ever spawned. The stronger property -- no
``openclaw`` shell-out exists at all -- becomes assertable only after P19-7b.
"""

from __future__ import annotations

import shutil
from pathlib import Path


class TestNoTestReachesTheRealOpenclawBinary:
    def test_resolved_openclaw_is_the_shim_not_the_real_binary(self) -> None:
        """``shutil.which`` is exactly what the ACL calls before shelling out."""
        resolved = shutil.which("openclaw")
        assert resolved is not None, "the autouse shim should always put an openclaw on PATH"
        text = Path(resolved).read_text()
        assert "test shim" in text, (
            f"PATH resolves 'openclaw' to {resolved}, which is not the test shim. "
            "A test reaching the real binary can mutate the developer's live "
            "~/.openclaw/openclaw.json -- see this module's docstring."
        )

    def test_the_shim_answers_version_without_touching_real_state(self) -> None:
        """The shim must satisfy the probes the ACL actually makes, or tests
        would 'pass' by falling back to daemon-unavailable paths rather than
        by exercising the real code."""
        import subprocess

        res = subprocess.run(["openclaw", "--version"], capture_output=True, text=True, timeout=10)
        assert res.returncode == 0
        assert "test shim" in res.stdout

    def test_shim_is_writable_over_by_the_absent_binary_case(self, fake_openclaw: Path) -> None:
        """``fake_openclaw`` must return the *same* directory the autouse fixture
        created. If the two ever diverge, a test deleting ``fake_openclaw``'s
        directory to exercise the absent-binary case would silently uncover the
        developer's real binary underneath -- reintroducing the exact defect
        this module guards against, in the one scenario nobody would think to
        re-check."""
        resolved = shutil.which("openclaw")
        assert resolved is not None
        assert Path(resolved).parent == fake_openclaw, (
            f"fake_openclaw returned {fake_openclaw} but PATH resolves to "
            f"{Path(resolved).parent}; deleting one would expose the real binary"
        )
