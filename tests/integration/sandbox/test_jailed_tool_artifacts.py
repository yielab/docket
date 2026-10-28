"""A jailed command's result over the output cap is kept whole and read back through `read`."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from docket.agent.tools.builtins import toolbox
from docket.kernel.home import current_home, use_home
from docket.kernel.tool_outcome import artifact_path_in, artifact_scope
from docket.sandbox import landlock

SUBJECT = "docket.agent.tools.builtins.toolbox"

pytestmark = pytest.mark.skipif(not landlock.landlock_available(), reason="Landlock not available")


def test_a_jailed_result_over_the_cap_is_stored_whole_and_read_returns_the_rest(
    tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (current_home().pods_dir / "pod").mkdir(parents=True)
    cache = current_home().pod_cache_dir("pod")
    cache.mkdir(parents=True)
    cache.chmod(0o700)

    with (
        use_home(dataclasses.replace(current_home(), tool_max_output_chars=2500)),
        artifact_scope("pod"),
    ):
        out = toolbox.run_bash((work,), "seq 1 20000", timeout=60, sandbox="auto", cache_dir=cache)
        path = artifact_path_in(out.content)
        assert path is not None, out.content
        window = toolbox.read_file((work,), path, offset=15000, limit=2)

    assert "[truncated:" in out.content
    assert Path(path).read_text().splitlines()[-1] == "20000"
    assert window.content.splitlines()[:2] == ["15000\t15000", "15001\t15001"]
