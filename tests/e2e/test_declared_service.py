"""A pod reaches a declared HTTP service, and the credential never leaves the secret store."""

from __future__ import annotations

import http.server
import json
import textwrap
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.e2e_workdir import outward_pack, workdir_pod
from tests.support.model_server import FakeModel, call, say, write_file

_DRAFT = "To: ana@example.test\n\nWelcome aboard.\n"

_SERVICE_TOKEN = "svc_" + "Q4r5T6y7" * 4
_SERVICE_NEW_CONTACT = {"email": "ana@example.test", "name": "Ana"}
_SERVICE_OTHER_CONTACT = {"email": "bo@example.test", "name": "Bo"}


class _CrmHandler(http.server.BaseHTTPRequestHandler):
    """A fake CRM: ``GET /v1/contacts/<id>`` reads, ``POST /v1/contacts`` creates and echoes the
    credential it was sent, so a leak back to the model would show. Every request is recorded."""

    def _answer(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self, body: Any = None) -> None:
        self.server.calls.append(  # type: ignore[attr-defined]
            {
                "method": self.command,
                "path": self.path,
                "authorization": self.headers.get("Authorization", ""),
                "task": self.headers.get("X-Docket-Task", ""),
                "body": body,
            }
        )

    def do_GET(self) -> None:
        self._record()
        self._answer(200, {"id": 7, "name": "Ana", "venue": "holds 80 people"})

    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self._record(json.loads(raw))
        echoed = self.headers.get("Authorization", "")
        self._answer(201, {"created": True, "echo": echoed})

    def log_message(self, format: str, *args: Any) -> None:
        """Keep the test output quiet."""


@pytest.fixture()
def crm_server() -> Iterator[http.server.HTTPServer]:
    """The fake CRM on 127.0.0.1 and an ephemeral port; ``calls`` lists what it received."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _CrmHandler)
    server.calls = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _crm_document(server: http.server.HTTPServer) -> str:
    return textwrap.dedent(
        f"""\
        kind: service
        name: crm
        baseUrl: http://127.0.0.1:{server.server_port}/v1
        hosts: [127.0.0.1]
        auth:
          header: Authorization
          value: Bearer ${{secret:crm}}
        operations:
          - name: get_contact
            method: GET
            path: /contacts/{{id}}
            params:
              - {{name: id, in: path, type: integer}}
          - name: create_contact
            method: POST
            path: /contacts
            body:
              type: object
              properties: {{email: {{type: string}}, name: {{type: string}}}}
              required: [email]
        """
    )


def _service_recipe(w: World) -> Path:
    """The ``outward`` pack with its Actor holding the service's POST in place of the MCP send,
    and its quota written the way its own comment says: ``service: crm``, one a day."""
    recipe = outward_pack(w, "svc__crm__create_contact")
    (recipe / "policies" / "send-quota.yaml").write_text(
        "kind: policy\nname: outward-send-quota\nappliesTo: [actor]\n"
        "limit: {service: crm, count: 1, per: day}\nthen: block\n",
        encoding="utf-8",
    )
    return recipe


def _home_text_without_secrets(w: World) -> Iterator[tuple[Path, str]]:
    """Every file under the docket home except the secret store, as text."""
    for path in sorted(w.home.rglob("*")):
        if path.is_file() and path.name != "secrets.json":
            yield path, path.read_bytes().decode("utf-8", errors="replace")


def test_an_outward_pod_reads_and_writes_through_a_declared_service_and_its_token_never_leaks(
    world: Callable[..., World],
    fake_model: Callable[..., FakeModel],
    crm_server: http.server.HTTPServer,
) -> None:
    calls: list[dict[str, Any]] = crm_server.calls  # type: ignore[attr-defined]
    model = fake_model(
        script={
            "lead": [say("Plan: add the guest.")],
            "researcher": [
                call("svc__crm__get_contact", "r1", id=7),
                say("The venue holds 80 people."),
            ],
            "writer": [write_file("draft.md", _DRAFT), say("draft.md is written.")],
            "reviewer": [say("APPROVE")],
            "actor": [
                call("svc__crm__create_contact", "a1", body=_SERVICE_NEW_CONTACT),
                call("svc__crm__create_contact", "a2", body=_SERVICE_NEW_CONTACT),
                call("svc__crm__create_contact", "a3", body=_SERVICE_OTHER_CONTACT),
                say("One contact was created; the second was over the quota."),
            ],
        }
    )
    w, _work_dir = workdir_pod(world, model, blueprint="respond")
    w.docket("setup", "secret", "set", "crm", "--stdin", stdin=_SERVICE_TOKEN)
    document = w.root / "crm.yaml"
    document.write_text(_crm_document(crm_server), encoding="utf-8")
    added = w.docket("setup", "service", "add", str(document))
    assert "create_contact" in added.out and _SERVICE_TOKEN not in added.out + added.err
    w.docket("pod", "update", str(_service_recipe(w)), "--pod", w.pod)
    task_id = w.add_task("Add the guest to the CRM")

    # the Researcher read through the service; the Actor's POST parks and nothing has been sent
    w.docket("run", "--pod", w.pod, "--timeout", "30", check=False)
    shown = w.task(task_id)["task"]
    assert shown["status"] == "waiting_approval", w.task(task_id)
    assert [(c["method"], c["path"]) for c in calls] == [("GET", "/v1/contacts/7")]
    assert calls[0]["authorization"] == f"Bearer {_SERVICE_TOKEN}"
    assert calls[0]["task"] == task_id

    # the approver sees the whole call, never the credential
    escalation = w.docket("inbox", "--peek", "--json").json()["escalations"][0]
    assert escalation["outward"] is True
    for ref in (escalation["id"], task_id):
        seen = w.docket("task", "show", ref, "--pod", w.pod).out
        assert "What leaves" in seen and "svc__crm__create_contact" in seen, seen
        assert "ana@example.test" in seen and _SERVICE_TOKEN not in seen

    # one yes sends it once, carrying the token and the task; the second POST is over the quota
    w.docket("task", "answer", escalation["id"], "--option", "approve_once", "--pod", w.pod)
    w.docket("run", "--pod", w.pod, "--timeout", "30")

    assert w.task(task_id)["task"]["status"] == "done", w.task(task_id)
    posts = [c for c in calls if c["method"] == "POST"]
    assert len(posts) == 1, calls
    assert posts[0]["path"] == "/v1/contacts" and posts[0]["body"] == _SERVICE_NEW_CONTACT
    assert posts[0]["authorization"] == f"Bearer {_SERVICE_TOKEN}"
    assert posts[0]["task"] == task_id
    rows = oracles.audit_rows(w)
    sends = [r for r in rows if r["action"] == "tool.send"]
    assert ["decision=allow" in r["detail"] for r in sends] == [True, False]
    assert "POST" in sends[0]["detail"] and "127.0.0.1" in sends[0]["detail"]
    refused = [r for r in rows if r["action"] == "tool.deny" and "1/1 per day" in r["detail"]]
    assert len(refused) == 1
    assert not w.docket("inbox", "--peek", "--json").json()["escalations"]

    # the roles that cannot act were never offered the POST; the Actor reads nothing
    for role in ("researcher", "writer", "reviewer"):
        requests = model.by_role(role)
        assert requests, role
        assert all("svc__crm__create_contact" not in r.tools for r in requests), role
    assert "svc__crm__get_contact" in model.by_role("researcher")[0].tools
    assert all("svc__crm__create_contact" in r.tools for r in model.by_role("actor"))
    assert not any("svc__crm__get_contact" in r.tools for r in model.by_role("actor"))

    # the token is in no model request, trace, audit line, inbox line or file of the home
    assert not any(_SERVICE_TOKEN in json.dumps(r.messages) for r in model.requests)
    echoes = [r.tool_result("a2") for r in model.by_role("actor")]
    echoed = next(e for e in echoes if e)
    assert "created" in echoed and "[REDACTED]" in echoed and _SERVICE_TOKEN not in echoed
    outputs = [
        w.docket("task", "trace", task_id, "--pod", w.pod, "--export").out,
        w.docket("task", "trace", task_id, "--pod", w.pod, "--json").out,
        w.docket("log", "--json").out,
        w.docket("inbox", "--peek", "--json").out,
        w.docket("status", "--pod", w.pod, "--json").out,
        w.docket("setup", "service", "list", "--json").out,
    ]
    assert all(_SERVICE_TOKEN not in text for text in outputs)
    leaks = [str(p) for p, text in _home_text_without_secrets(w) if _SERVICE_TOKEN in text]
    assert leaks == []
    stored = (w.home / "config" / "services.json").read_text(encoding="utf-8")
    assert "Bearer ${secret:crm}" in stored
    oracles.assert_log_verifies(w)
