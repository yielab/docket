"""The ``setup search`` group: a pod's web search, declared as a service."""

from __future__ import annotations

from typing import Annotated

import typer

from docket.governance.audit import audit_log
from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.commands import setup_secret as _setup_secret
from docket.interfaces.cli.commands import target as _target
from docket.interfaces.cli.render import ui
from docket.kernel.errors import InvalidInput, Unavailable
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


@search_app.command("brave")
def cmd_brave(
    refused: Annotated[str | None, typer.Argument(hidden=True)] = None,
    pod: str | None = _target.pod_option(),
    stdin: Annotated[
        bool, typer.Option("--stdin", help="Read the API key from standard input.")
    ] = False,
) -> None:
    """Set a pod up to search through the Brave Search API; the key comes from a hidden prompt or --stdin.

    Stores the key as the secret brave-search and writes the pod's services/search.yaml for Brave,
    replacing a SearXNG one. The key is never an argument and never leaves this machine except in
    the header of a search call; docket makes no call to Brave here. Brave's terms govern what
    may be kept of its results (see the web-research recipe README).
    Example: printf '%s' "$BRAVE_KEY" | docket setup search brave --stdin --pod research"""
    if refused is not None:
        ui.error(
            "A key is never an argument",
            "Pipe it: docket setup search brave --stdin",
        )
        raise typer.Exit(2)
    project = _contract.require_pod(pod)
    if not _pp.pod_member_ids(project):
        ui.error(f"No pod named '{project}'", "Create one with: docket init")
        raise typer.Exit(1)
    name = _services.BRAVE_SECRET
    key = _setup_secret.read_value(name, stdin, "docket setup search brave")
    if not key:
        ui.error("Value cannot be empty")
        raise typer.Exit(1)
    try:
        action = _search.setup_brave(project, key)
    except (PodApplyError, InvalidInput) as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    except Unavailable as exc:
        ui.error(exc.message, exc.hint)
        raise typer.Exit(1) from exc
    audit_log("search.setup", f"pod={project!r} provider='brave'")
    ui.success(f"Stored {name}.")
    verb = {"add": "added", "replace": "replaced", "skip": "unchanged"}[action]
    ui.success(f"Service 'search' {verb} for pod '{project}' ({_services.BRAVE_URL}).")
    _contract.next_step(f"docket pod show --pod {project}")
