"""A repository's ``.docket/`` can declare a pod's `fetch` hosts but never the any-host grant.

``pod update`` and ``POST /pods/<p>/apply`` share ``teams.apply.plan``, so planning and applying
a directory is the oracle for both (security-gates.spec.md "Network egress and the `fetch` tool").
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from tests.support.pods import seed_fixture_pod as _seed_fixture_pod

from docket.kernel.home import current_home
from docket.teams import pod, pod_settings
from docket.teams.apply import plan as _pod_apply
from docket.teams.apply import review as _review
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


_HOSTS = "  fetchDomains: [docs.python.org, '*.wikipedia.org']\n"


def test_the_review_lists_declared_hosts_as_a_run_item_not_an_add(tmp_path: Path) -> None:
    review = _review.classify_directory(_directory(tmp_path, _HOSTS))
    assert [(r.kind, r.name, r.runs) for r in review.runs] == [
        ("fetch-domains", "fetchDomains", "*.wikipedia.org, docs.python.org")
    ]
    assert ("setting", "fetchDomains") not in review.adds


def test_an_empty_host_list_is_not_a_run_item(tmp_path: Path) -> None:
    review = _review.classify_directory(_directory(tmp_path, "  fetchDomains: []\n"))
    assert review.runs == ()


def test_declared_hosts_apply_only_after_the_operator_accepts(tmp_path: Path) -> None:
    with _seed_fixture_pod(tmp_path, "reader"):
        directory = _directory(tmp_path, _HOSTS)
        asked = _pod_apply.apply_directory(
            "reader", directory, tmp_path, accept=None, dry_run=False, channel="cli"
        )
        assert asked.status == "needs_code"
        assert [r.kind for r in asked.runs] == ["fetch-domains"]
        assert pod_settings.effective_fetch_domains("reader") == ()

        done = _pod_apply.apply_directory(
            "reader", directory, tmp_path, accept=asked.code, dry_run=False, channel="cli"
        )
        assert done.status == "applied"
        assert pod_settings.effective_fetch_domains("reader") == (
            "docs.python.org",
            "*.wikipedia.org",
        )


@pytest.mark.parametrize("hosts", [[], ["docs.python.org"]])
def test_an_export_never_carries_the_any_host_grant(tmp_path: Path, hosts: list[str]) -> None:
    with _seed_fixture_pod(tmp_path, "reader"):
        pod_settings.grant_fetch_any("reader", by="cli")
        lead = current_home().meta_path(pod.member_id("reader", "lead"))
        meta = json.loads(lead.read_text())
        meta["fetchDomains"] = ",".join([*hosts, "*"])
        lead.write_text(json.dumps(meta))

        out = tmp_path / "exported"
        _write.export_pod("reader", out)

        settings = yaml.safe_load((out / "pod.yaml").read_text()).get("settings", {})
        exported = [h for h in str(settings.get("fetchDomains", "")).split(",") if h]
        assert exported == hosts

        pod_settings.revoke_fetch_grant("reader")  # a machine without the grant takes it
        plan = _pod_apply.plan_apply("reader", out)
        assert all(i.name != "fetchGrant" for i in plan.items)
