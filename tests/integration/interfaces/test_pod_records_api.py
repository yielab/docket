"""GET /pods/<pod>/records and /pods/<pod>/records/<set>: a pod's records over HTTP, read-only."""

from __future__ import annotations

from urllib.parse import quote

from tests.support import http as _support_http
from tests.support import pods as _support_pods
from tests.support.http import get as _get

from docket.kernel.home import current_home
from docket.platform.records_store import RecordMeta, RecordsStore
from docket.teams import pod_provisioning as _pp
from docket.teams import records as _records

live_server = _support_http.live_server

pod_home = _support_pods.pod_home

SUBJECT = "docket.interfaces.http.routes.pod_records"

_LEADS = """\
kind: records
name: leads
description: People the pod has contacted.
key: email
columns:
  - {name: email, type: string, required: true}
  - {name: score, type: integer}
"""


def _pod_with_leads(name: str = "demo", rows: int = 2) -> None:
    _pp.provision_pod(name, "software", location=f"/src/{name}")
    directory = _records.pod_records_dir(name)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "leads.yaml").write_text(_LEADS, encoding="utf-8")
    _records.ensure_set(name, _records.pod_record_sets(name)[0][0])
    store = RecordsStore(current_home().pod_records_path(name))
    for i in range(rows):
        store.add("leads", {"email": f"p{i}@x.test", "score": i}, RecordMeta(task="t1"))


def _count(name: str = "demo") -> int:
    store = RecordsStore(current_home().pod_records_path(name))
    return int(store.query("SELECT count(*) FROM leads", 5, 1000).rows[0][0])


def test_list_names_the_set_with_columns_and_row_count(live_server: tuple[str, str]) -> None:
    url, token = live_server
    _pod_with_leads()

    status, body = _get(f"{url}/pods/demo/records", token)

    assert status == 200
    assert body["problems"] == []
    [leads] = body["records"]
    assert (leads["name"], leads["rows"], leads["key"]) == ("leads", 2, "email")
    assert leads["columns"] == [
        {"name": "email", "type": "string", "required": True},
        {"name": "score", "type": "integer", "required": False},
    ]


def test_list_of_a_pod_without_records_is_empty(live_server: tuple[str, str]) -> None:
    url, token = live_server
    _pp.provision_pod("quiet", "software", location="/src/quiet")

    assert _get(f"{url}/pods/quiet/records", token) == (200, {"records": [], "problems": []})


def test_rows_route_returns_both_rows_and_honours_limit(live_server: tuple[str, str]) -> None:
    url, token = live_server
    _pod_with_leads()

    status, body = _get(f"{url}/pods/demo/records/leads", token)
    assert status == 200
    assert body["set"] == "leads"
    assert [r["email"] for r in body["rows"]] == ["p1@x.test", "p0@x.test"]
    assert body["cut"] == 0
    assert "email" in body["columns"]

    status, body = _get(f"{url}/pods/demo/records/leads?limit=1", token)
    assert status == 200
    assert [r["email"] for r in body["rows"]] == ["p1@x.test"]
    assert body["cut"] == 1


def test_sql_runs_through_the_read_only_query(live_server: tuple[str, str]) -> None:
    url, token = live_server
    _pod_with_leads()
    sql = quote("SELECT email FROM leads WHERE score = 1")

    status, body = _get(f"{url}/pods/demo/records/leads?sql={sql}", token)

    assert status == 200
    assert body["columns"] == ["email"]
    assert body["rows"] == [{"email": "p1@x.test"}]


def test_a_refused_statement_is_400_and_the_rows_remain(live_server: tuple[str, str]) -> None:
    url, token = live_server
    _pod_with_leads()

    for statement in ("DELETE FROM leads", "SELECT 1; SELECT 2"):
        status, body = _get(f"{url}/pods/demo/records/leads?sql={quote(statement)}", token)
        assert status == 400
        assert body["ok"] is False
        assert body["error"]
    assert _count() == 2


def test_bad_limit_is_400(live_server: tuple[str, str]) -> None:
    url, token = live_server
    _pod_with_leads()

    for limit in ("0", "-1", "abc", "1001"):
        status, _ = _get(f"{url}/pods/demo/records/leads?limit={limit}", token)
        assert status == 400, limit


def test_no_token_is_401(live_server: tuple[str, str]) -> None:
    url, _token = live_server
    _pod_with_leads()

    assert _get(f"{url}/pods/demo/records")[0] == 401
    assert _get(f"{url}/pods/demo/records/leads")[0] == 401
    assert _get(f"{url}/pods/demo/records/leads", "wrong")[0] == 401


def test_unknown_set_and_unknown_pod_are_404(live_server: tuple[str, str]) -> None:
    url, token = live_server
    _pod_with_leads()

    status, body = _get(f"{url}/pods/demo/records/ghost", token)
    assert status == 404
    assert "ghost" in body["error"]
    assert "leads" in body["error"]
    assert _get(f"{url}/pods/nobody/records", token)[0] == 404
    assert _get(f"{url}/pods/nobody/records/leads", token)[0] == 404


def test_a_set_is_read_from_the_pod_the_path_names(live_server: tuple[str, str]) -> None:
    url, token = live_server
    _pod_with_leads("demo", rows=2)
    _pod_with_leads("other", rows=1)

    _, body = _get(f"{url}/pods/other/records/leads", token)

    assert [r["email"] for r in body["rows"]] == ["p0@x.test"]


def test_a_declared_set_with_no_file_reads_as_no_rows(live_server: tuple[str, str]) -> None:
    url, token = live_server
    _pp.provision_pod("fresh", "software", location="/src/fresh")
    directory = _records.pod_records_dir("fresh")
    directory.mkdir(parents=True)
    (directory / "leads.yaml").write_text(_LEADS, encoding="utf-8")

    status, body = _get(f"{url}/pods/fresh/records/leads", token)

    assert status == 200
    assert body["rows"] == []
    assert _get(f"{url}/pods/fresh/records", token)[1]["records"][0]["rows"] == 0
