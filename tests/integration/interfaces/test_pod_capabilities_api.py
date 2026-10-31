"""GET /pods/<pod>: what each member's role can reach, from the function that narrows its tools."""

from __future__ import annotations

from typing import Any

from tests.support import http as _support_http
from tests.support import pods as _support_pods
from tests.support.http import get as _get
from tests.support.roles import write_role_overlay

from docket.teams import pod_provisioning as _pp
from docket.teams import records as _records

live_server = _support_http.live_server

pod_home = _support_pods.pod_home

SUBJECT = "docket.hops.application.report"

_PROPOSALS = """\
kind: records
name: tack_proposals
key: ref
scope: task
columns:
  - {name: ref, type: string, required: true}
  - {name: title, type: string, required: true}
"""


def _pod_with_proposals(name: str = "demo") -> None:
    _pp.provision_pod(name, "build", location=f"/src/{name}")
    directory = _records.pod_records_dir(name)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "tack_proposals.yaml").write_text(_PROPOSALS, encoding="utf-8")


def _members(url: str, token: str, name: str = "demo") -> dict[str, dict[str, Any]]:
    status, body = _get(f"{url}/pods/{name}", token)
    assert status == 200
    return {m["role"]: m["capabilities"] for m in body["members"]}


def test_a_read_only_role_can_still_write_proposal_rows(live_server: tuple[str, str]) -> None:
    _pod_with_proposals()

    reviewer = _members(*live_server)["reviewer"]

    assert reviewer["records"] == {"write": ["tack_proposals"], "query": True}
    assert "record" in reviewer["kinds"]
    assert not {"write", "exec"} & set(reviewer["kinds"])
    assert "write" not in reviewer["tools"]
    assert "rec__tack_proposals__add" in reviewer["tools"]


def test_a_role_that_acts_on_the_project_says_so(live_server: tuple[str, str]) -> None:
    _pod_with_proposals()

    implementer = _members(*live_server)["implementer"]

    assert {"write", "exec", "record"} <= set(implementer["kinds"])
    assert {"write", "edit", "bash"} <= set(implementer["tools"])


def test_denying_the_record_kind_removes_the_write_entry(live_server: tuple[str, str]) -> None:
    _pod_with_proposals()
    write_role_overlay("demo", "reviewer", ["write", "record"])

    reviewer = _members(*live_server)["reviewer"]

    assert reviewer["records"] == {"write": [], "query": True}
    assert "record" not in reviewer["kinds"]


def test_a_pod_with_no_record_set_has_no_record_capability(live_server: tuple[str, str]) -> None:
    _pp.provision_pod("plain", "build", location="/src/plain")

    lead = _members(*live_server, name="plain")["lead"]

    assert lead["records"] == {"write": [], "query": False}
