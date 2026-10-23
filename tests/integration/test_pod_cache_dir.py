"""A pod's cache directory: created 0700 at provisioning, and the home a jailed command writes to."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from docket.agent.tools.builtins import toolbox
from docket.kernel.home import current_home
from docket.sandbox import landlock
from docket.teams import pod_provisioning as _prov

SUBJECT = "docket.agent.tools.builtins.toolbox"


def test_provisioning_creates_the_cache_dir_0700() -> None:
    _prov.allocate_pod_resources("cachepod")

    cache = current_home().pod_cache_dir("cachepod")
    assert cache.is_dir()
    assert oct(cache.stat().st_mode & 0o777) == "0o700"


@pytest.mark.skipif(not landlock.landlock_available(), reason="Landlock not available")
def test_a_jailed_command_writes_its_cache_under_the_pod_cache(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    cache = tmp_path / "pod" / "cache"
    cache.mkdir(parents=True)
    cache.chmod(0o700)
    command = 'mkdir -p "$XDG_CACHE_HOME/uv" && echo x > "$UV_CACHE_DIR/f" && echo "$HOME"'

    out = toolbox.run_bash((work,), command, timeout=60, sandbox="auto", cache_dir=cache)

    assert out.ok, out.error
    assert (cache / "f").read_text().strip() == "x"
    assert str(cache) in out.content


@pytest.mark.skipif(not landlock.landlock_available(), reason="Landlock not available")
def test_the_real_home_stays_unwritable_in_the_jail(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    real_home = os.path.expanduser("~")
    if not shutil.which("sh") or not os.path.isdir(real_home):
        pytest.skip("no home to probe")
    probe = Path(real_home) / ".docket-cache-probe"

    out = toolbox.run_bash((work,), f"touch {probe}", timeout=60, sandbox="auto", cache_dir=cache)

    assert not out.ok
    assert not probe.exists()


def test_the_driver_resolves_and_creates_a_members_pod_cache() -> None:
    from docket.agent import isolation_posture as _isolation_posture

    cache = _isolation_posture._pod_cache_dir("cachepod-implementer")

    assert cache == current_home().pod_cache_dir("cachepod")
    assert oct(cache.stat().st_mode & 0o777) == "0o700"
    assert _isolation_posture._pod_cache_dir("not-a-pod-member") is None
