"""``docket pod set fetchDomains``: hosts for a pod's `fetch`, and `*` only with the operator's yes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support.cli import invoke_pod
from tests.support.pods import build_pod
from tests.support.pods import seed_empty_home as _seed

from docket.governance.audit import read_audit
from docket.interfaces.cli.commands import contract as _contract
from docket.kernel.home import current_home
from docket.teams import pod, pod_settings

SUBJECT = "docket.interfaces.cli.commands.pod"


def _meta() -> dict[str, object]:
    return dict(json.loads(current_home().meta_path("proj-lead").read_text()))


def _actions() -> list[str]:
    return [str(e["action"]) for e in read_audit() if str(e["action"]).startswith("pod.fetch_")]


def test_hosts_are_set_cleared_and_a_bare_star_is_refused(tmp_path: Path) -> None:
    with _seed(tmp_path):
        build_pod("proj", pod.DEFAULT_POD_ROLES, codebase="/src/proj")
        done = invoke_pod(
            ["set", "fetchDomains", "docs.python.org,*.wikipedia.org", "--pod", "proj"]
        )
        assert done.exit_code == 0, done.output
        assert pod_settings.effective_fetch_domains("proj") == (
            "docs.python.org",
            "*.wikipedia.org",
        )
        refused = invoke_pod(["set", "fetchDomains", "*", "--pod", "proj"])
        assert refused.exit_code == 1 and "--widen" in refused.output
        assert pod_settings.effective_fetch_domains("proj")[0] == "docs.python.org"
        assert invoke_pod(["unset", "fetchDomains", "--pod", "proj"]).exit_code == 0
        assert pod_settings.effective_fetch_domains("proj") == ()


def test_widen_asks_and_a_no_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _seed(tmp_path):
        build_pod("proj", pod.DEFAULT_POD_ROLES, codebase="/src/proj")
        monkeypatch.setattr(_contract, "is_tty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
        before = _meta()
        result = invoke_pod(["set", "fetchDomains", "*", "--widen", "--pod", "proj"])
        assert result.exit_code == 1 and "any public host" in result.output
        assert _meta() == before and _actions() == []


def test_widen_with_yes_records_audits_and_a_later_list_narrows(tmp_path: Path) -> None:
    with _seed(tmp_path):
        build_pod("proj", pod.DEFAULT_POD_ROLES, codebase="/src/proj")
        wrong = invoke_pod(["set", "fetchDomains", "a.org", "--widen", "--yes", "--pod", "proj"])
        assert wrong.exit_code == 1
        result = invoke_pod(["set", "fetchDomains", "*", "--widen", "--yes", "--pod", "proj"])
        assert result.exit_code == 0, result.output
        grant = _meta()["fetchGrant"]
        assert isinstance(grant, dict) and grant["at"] and grant["by"]
        assert pod_settings.effective_fetch_domains("proj") == ("*",)
        assert invoke_pod(["set", "fetchGrant", "x", "--pod", "proj"]).exit_code == 1
        narrowed = invoke_pod(["set", "fetchDomains", "docs.python.org", "--pod", "proj"])
        assert narrowed.exit_code == 0, narrowed.output
        assert "fetchGrant" not in _meta()
        assert pod_settings.effective_fetch_domains("proj") == ("docs.python.org",)
        assert _actions() == ["pod.fetch_widen", "pod.fetch_narrow"]
