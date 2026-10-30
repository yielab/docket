"""POST /escalations/<id> -- settling an escalation over HTTP (operator-api.spec.md).

A real server on a loopback port over a seeded pod. The oracles are the status code, the body, the
escalation record and the task, and that the retired routes (`POST /approvals/<token>`, `GET /approvals`,
`POST /tasks/<id>/answer`) are ordinary unknowns that change nothing.
"""

from __future__ import annotations

import urllib.error
import urllib.request

import pytest
from tests.support import escalations as _support_escalations
from tests.support import http as _support_http
from tests.support import pods as _support_pods
from tests.support.escalations import (
    PROJECT,
    approval_escalation,
    consult_escalation,
    input_escalation,
)
from tests.support.http import get as _get
from tests.support.http import post as _post
from tests.support.tasks import stored_task

from docket.governance import approval as _ap
from docket.governance import policy as _policy
from docket.platform import read_escalation
from docket.tasks.application.answers import answers_of

live_server = _support_http.live_server
pod_home = _support_pods.pod_home

SUBJECT = "docket.interfaces.http.routes.escalations"


demo_pod = _support_escalations.demo_pod
pytestmark = pytest.mark.usefixtures("pod_home", "demo_pod")


class TestResolveRoute:
    def test_it_needs_the_bearer_token(self, live_server: tuple[str, str]) -> None:
        url, _token = live_server

        status, body = _post(f"{url}/escalations/esc-000000000000", {"optionId": "deny"})

        assert (status, body["ok"]) == (401, False)

    def test_an_approval_is_granted_and_the_view_comes_back_resolved(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        escalation = approval_escalation("gate")

        status, body = _post(
            f"{url}/escalations/{escalation.id}",
            {"optionId": "approve_once", "actor": "tack-board"},
            token=token,
        )

        assert status == 200
        assert (body["id"], body["state"]) == (escalation.id, "resolved")
        assert body["resolution"]["optionId"] == "approve_once"
        assert (body["resolution"]["by"], body["resolution"]["channel"]) == ("tack-board", "http")
        assert body["affordances"] == {
            "options": [],
            "acceptsText": False,
            "resolveUrl": f"/escalations/{escalation.id}",
        }
        task = stored_task(PROJECT, escalation.task)
        assert task.status == "pending"
        assert _ap.approval_get(_ap.approval_of(escalation.id))["state"] == "granted"

    def test_a_denial_carries_its_reason_to_the_failed_task(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        escalation = approval_escalation("gate")

        status, _body = _post(
            f"{url}/escalations/{escalation.id}",
            {"optionId": "deny", "content": {"reason": "not today"}},
            token=token,
        )

        assert status == 200
        task = stored_task(PROJECT, escalation.task)
        assert (task.status, task.reason) == ("failed", "approval denied: not today")

    def test_a_consult_is_answered_with_an_option_and_content(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        escalation = consult_escalation()

        status, body = _post(
            f"{url}/escalations/{escalation.id}",
            {"optionId": "redis", "content": {"note": "hot path"}},
            token=token,
        )

        assert status == 200
        assert body["resolution"]["content"] == {"note": "hot path"}
        task = stored_task(PROJECT, escalation.task)
        assert (task.status, [a.option_id for a in answers_of(task)]) == ("pending", ["redis"])

    def test_cancel_is_a_decline(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        escalation = input_escalation()

        status, body = _post(
            f"{url}/escalations/{escalation.id}", {"optionId": "cancel"}, token=token
        )

        assert status == 200
        assert body["resolution"]["optionId"] == "decline"
        assert [a.action for a in answers_of(stored_task(PROJECT, escalation.task))] == ["decline"]

    def test_a_second_resolve_is_a_conflict_and_changes_nothing(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        escalation = approval_escalation("gate")
        _post(f"{url}/escalations/{escalation.id}", {"optionId": "approve_once"}, token=token)
        settled = read_escalation(escalation.id)

        status, body = _post(
            f"{url}/escalations/{escalation.id}", {"optionId": "deny"}, token=token
        )

        assert (status, body["ok"]) == (409, False)
        assert "apr-" not in body["error"]
        assert read_escalation(escalation.id) == settled

    def test_an_unknown_escalation_is_not_found(self, live_server: tuple[str, str]) -> None:
        url, token = live_server

        status, _body = _post(
            f"{url}/escalations/esc-000000000000", {"optionId": "deny"}, token=token
        )

        assert status == 404

    def test_an_option_the_escalation_does_not_offer_is_unprocessable(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        escalation = consult_escalation()

        status, body = _post(
            f"{url}/escalations/{escalation.id}", {"optionId": "mongo"}, token=token
        )

        assert status == 422
        assert "redis, sqlite, decline" in body["error"]
        assert stored_task(PROJECT, escalation.task).status == "waiting_input"

    def test_content_breaking_the_schema_is_unprocessable(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        escalation = input_escalation()

        status, _body = _post(f"{url}/escalations/{escalation.id}", {"content": {}}, token=token)

        assert status == 422
        assert stored_task(PROJECT, escalation.task).status == "waiting_input"

    def test_content_a_policy_blocks_is_unprocessable_naming_it(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url, token = live_server
        escalation = input_escalation()
        monkeypatch.setattr(
            _policy,
            "policy_eval_detail",
            lambda *a, **k: _policy.PolicyHit(action="block", policy_id="canary"),
        )

        status, body = _post(
            f"{url}/escalations/{escalation.id}", {"content": {"answer": "x"}}, token=token
        )

        assert status == 422
        assert "canary" in body["error"]

    @pytest.mark.parametrize(
        "body",
        [
            {"optionId": 3},
            {"optionId": "deny", "content": "text"},
            {"optionId": "deny", "actor": 7},
        ],
    )
    def test_an_ill_typed_field_is_a_bad_request(
        self, live_server: tuple[str, str], body: dict[str, object]
    ) -> None:
        url, token = live_server
        escalation = approval_escalation("gate")

        status, _body = _post(f"{url}/escalations/{escalation.id}", body, token=token)

        assert status == 400
        assert read_escalation(escalation.id) == escalation


class TestTheRetiredRoutesAreOrdinaryUnknowns:
    def test_posting_a_decision_on_a_token_is_not_found_and_changes_nothing(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        escalation = approval_escalation("gate")
        approval = _ap.approval_of(escalation.id)

        status, _body = _post(f"{url}/approvals/{approval}", {"action": "grant"}, token=token)

        assert status == 404
        assert _ap.approval_get(approval)["state"] == "pending"
        assert read_escalation(escalation.id) == escalation

    def test_listing_the_approvals_is_not_found(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        approval_escalation("gate")

        req = urllib.request.Request(f"{url}/approvals")
        req.add_header("Authorization", f"Bearer {token}")
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)

        assert caught.value.code == 404

    def test_answering_a_task_is_not_found_and_changes_nothing(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        escalation = input_escalation()

        status, _body = _post(
            f"{url}/tasks/{escalation.task}/answer",
            {"pod": PROJECT, "action": "accept", "content": {"answer": "ship it"}},
            token=token,
        )
        unknown, _ = _post(f"{url}/tasks/{escalation.task}/frobnicate", {}, token=token)

        assert status == unknown >= 400
        assert stored_task(PROJECT, escalation.task).status == "waiting_input"
        assert read_escalation(escalation.id) == escalation


class TestOneEscalationRoute:
    CALL = 'mcp__outbox__send to="ana@example.test" phone="+57 300 1234567"'

    def test_it_needs_the_bearer_token(self, live_server: tuple[str, str]) -> None:
        url, _token = live_server

        assert _get(f"{url}/escalations/esc-000000000000")[0] == 401

    def test_an_unknown_id_is_a_404(self, live_server: tuple[str, str]) -> None:
        url, token = live_server

        assert _get(f"{url}/escalations/esc-000000000000", token)[0] == 404
        assert _get(f"{url}/escalations/not-an-id", token)[0] == 404

    def test_a_pending_outward_approval_carries_its_call_and_no_list_does(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        escalation = approval_escalation("approval", call=self.CALL)

        status, one = _get(f"{url}/escalations/{escalation.id}", token)
        _, listed = _get(f"{url}/escalations", token)
        _, inbox = _get(f"{url}/inbox", token)

        assert status == 200
        assert (one["id"], one["state"], one["outward"], one["call"]) == (
            escalation.id,
            "pending",
            True,
            self.CALL,
        )
        assert "call" not in listed["escalations"][0] and "call" not in inbox["escalations"][0]
        assert listed["escalations"][0]["outward"] is True

    def test_a_settled_approval_no_longer_has_a_call(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        escalation = approval_escalation("approval", call=self.CALL)

        _post(f"{url}/escalations/{escalation.id}", {"optionId": "deny"}, token=token)
        status, one = _get(f"{url}/escalations/{escalation.id}", token)

        assert (status, one["state"]) == (200, "resolved")
        assert "call" not in one

    def test_an_approval_that_keeps_no_call_answers_without_one(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        escalation = approval_escalation("gate")

        _, one = _get(f"{url}/escalations/{escalation.id}", token)

        assert "call" not in one and "outward" not in one
