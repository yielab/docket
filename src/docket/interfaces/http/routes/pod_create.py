"""``POST /pods`` -- provision a fresh pod from a blueprint."""

from __future__ import annotations

import json

from docket.interfaces.http.exchange import HttpExchange
from docket.teams import blueprints as _bp
from docket.teams import pod_provisioning as _pp
from docket.teams import provisioning as _prov
from docket.teams.pod import FULL_POD_ROLES


def post_pod(h: HttpExchange, _arg: str) -> None:
    """Body, response shape, and the not-a-thin-wrapper/no-drift rationale:
    specs/data/serve-read-api.spec.md (POST /pods)."""
    body = h._read_json_object()
    if body is None:
        return

    project = body.get("name")
    if not isinstance(project, str) or not project:
        h._send_json_error("name is required", 400)
        return

    blueprint_name = body.get("blueprint", _bp.DEFAULT_BLUEPRINT)
    if not isinstance(blueprint_name, str) or not blueprint_name:
        h._send_json_error("blueprint must be a non-empty string", 400)
        return

    path_value = body.get("location", "")
    if not isinstance(path_value, str):
        h._send_json_error("location must be a string", 400)
        return

    # `pod` mirrors `docket init --pod full` — the CLI's only roster
    # override, itself restricted to the `software` blueprint (a
    # non-`software` blueprint provisions its own fixed roster; the CLI
    # warns and ignores rather than erroring, and there is no HTTP
    # surface to print that warning to, so this route just ignores it
    # the same way).
    pod_field = body.get("pod")
    roles: tuple[str, ...] | None = None
    if pod_field is not None:
        if not isinstance(pod_field, str) or pod_field.lower() != "full":
            h._send_json_error('pod must be "full" if given', 400)
            return
        if blueprint_name == "software":
            roles = FULL_POD_ROLES

    budget_raw = body.get("budget")
    budget_usd: float | None = None
    if budget_raw is not None:
        if isinstance(budget_raw, bool) or not isinstance(budget_raw, (int, float, str)):
            h._send_json_error("budget must be a number", 400)
            return
        try:
            budget_val = float(budget_raw)
        except (TypeError, ValueError):
            h._send_json_error("budget must be numeric", 400)
            return
        budget_usd = budget_val if budget_val > 0 else None

    verify_cmd = body.get("verifyCmd", "")
    if not isinstance(verify_cmd, str):
        h._send_json_error("verifyCmd must be a string", 400)
        return

    ensure = body.get("ensure", False)
    if not isinstance(ensure, bool):
        h._send_json_error("ensure must be a boolean", 400)
        return

    try:
        result = _pp.provision_pod(
            project,
            blueprint_name,
            location=path_value,
            roles=roles,
            budget_usd=budget_usd,
            verify_cmd=verify_cmd,
            source="http",
        )
    except _bp.BlueprintError as exc:
        h._send_json_error(str(exc), 400)
        return
    except _pp.VerifyCmdError as exc:
        h._send_json_error(str(exc), 400)
        return
    except _prov.ProjectIdError as exc:
        h._send_json_error(str(exc), 400)
        return
    except _pp.PodAlreadyExistsError:
        if ensure:
            h._send(
                json.dumps({"ok": True, "created": False, "project": project}).encode(),
                "application/json",
            )
            return
        h._send_json_error(f"'{project}' already exists", 409)
        return
    except _pp.PodProvisionError as exc:
        # Rollback has already run (see provision_pod's docstring) --
        # nothing from this attempt survives on disk or in the fleet
        # registry. Not a 4xx: the request itself was well-formed, the
        # failure is an operational one (e.g. disk/filesystem trouble).
        h._send_json_error(str(exc), 500)
        return

    resp_body = json.dumps(
        {
            "ok": True,
            "created": True,
            "project": result.project,
            "blueprint": result.blueprint,
            "members": [
                {"id": m.member_id, "role": m.role, "model": m.model} for m in result.members
            ],
        }
    ).encode()
    h._send(resp_body, "application/json", status=201)
