"""A repository's ``.docket/`` can declare a pod's `fetch` hosts but never the any-host grant.

``pod update`` and ``POST /pods/<p>/apply`` share ``teams.apply.plan``, so planning and applying
a directory is the oracle for both (security-gates.spec.md "Network egress and the `fetch` tool").
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support.pods import seed_fixture_pod as _seed_fixture_pod

from docket.kernel.home import current_home
from docket.teams import pod, pod_settings
from docket.teams.apply import plan as _pod_apply
from docket.teams.apply import write as _write

SUBJECT = "docket.teams.apply.plan"


def _directory(tmp_path: Path, settings: str) -> Path:
    directory = tmp_path / "repo-docket"
    directory.mkdir()
    (directory / "pod.yaml").write_text(
        f"kind: pod\nname: x\nsettings:\n{settings}", encoding="utf-8"
    )
    return directory


def test_a_directory_declares_the_hosts_a_pod_reads(tmp_path: Path) -> None:
    with _seed_fixture_pod(tmp_path, "reader"):
        directory = _directory(tmp_path, "  fetchDomains: [docs.python.org, '*.wikipedia.org']\n")
        _write.apply(_pod_apply.plan_apply("reader", directory))
        assert pod_settings.effective_fetch_domains("reader") == (
            "docs.python.org",
            "*.wikipedia.org",
        )


@pytest.mark.parametrize(
    "settings",
    [
        "  fetchDomains: ['*']\n",
        "  fetchDomains: '*'\n",
        '  fetchGrant: \'{"at": "x", "by": "y"}\'\n',
    ],
)
def test_a_directory_cannot_write_the_any_host_grant(tmp_path: Path, settings: str) -> None:
    with _seed_fixture_pod(tmp_path, "reader"):
        with pytest.raises(_pod_apply.PodApplyError):
            _pod_apply.plan_apply("reader", _directory(tmp_path, settings))
        meta = json.loads(current_home().meta_path(pod.member_id("reader", "lead")).read_text())
        assert "fetchGrant" not in meta
        assert "*" not in str(meta.get("fetchDomains", ""))
