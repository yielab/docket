"""The ``setup search`` group: a pod's web search, declared as a service."""

from __future__ import annotations

import typer

from docket.governance.audit import audit_log
from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.commands import target as _target
from docket.interfaces.cli.render import ui
from docket.kernel.errors import InvalidInput
from docket.teams import pod_provisioning as _pp
from docket.teams import services as _services
from docket.teams.apply import search as _search
from docket.teams.apply.model import PodApplyError

search_app = typer.Typer(
    name="search",
    help="Web search for a pod's researchers, declared as the service 'search'.",
    no_args_is_help=True,
)


@search_app.command("searxng")
def cmd_searxng(pod: str | None = _target.pod_option()) -> None:
    """Set a pod up to search through a local SearXNG, free, and print the docker command that serves it.

    Writes the SearXNG settings under the home and the pod's services/search.yaml, then prints
    the one docker run line; docket never starts or supervises the container. Running it again
    changes nothing.
    Example: docket setup search searxng --pod research"""
    project = _contract.require_pod(pod)
    if not _pp.pod_member_ids(project):
        ui.error(f"No pod named '{project}'", "Create one with: docket init")
        raise typer.Exit(1)
    try:
        done = _search.setup_searxng(project)
    except (PodApplyError, InvalidInput) as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    audit_log("search.setup", f"pod={project!r} provider='searxng'")
    ui.success(
        f"SearXNG settings {'written' if done.settings_written else 'kept'}: {done.settings}"
    )
    verb = {"add": "added", "replace": "replaced", "skip": "unchanged"}[done.service_action]
    ui.success(f"Service 'search' {verb} for pod '{project}' ({_services.SEARXNG_URL}).")
    ui.info("Start it once (docket does not run containers):")
    typer.echo(_search.docker_run_line(done.settings))
    _contract.next_step(f"docket pod show --pod {project}")
