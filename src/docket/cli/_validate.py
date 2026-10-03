"""docket validate — check every role, pipeline, policy, and pod configuration document.

  docket validate [dir|file]   Default target: <cwd>/.docket if it exists, else the cwd.
                                A directory validates every roles/*, policies/*, pipeline.yaml,
                                and pod.yaml under it; a file argument validates that one file.

``run_validate(args)`` returns the process exit code. Wires ``core/config_docs.py``'s
``load_document``/``discover_config_paths`` -- the same dispatch ``docket roles add/validate``,
``docket pipeline validate``, ``docket policies validate``, and ``docket pod <p> apply`` use, so
one file always means the same thing regardless of which command reads it. A directory target
also prints a derived ``summary:`` line (``core.pod_apply.summarize_recipe``) plus the recipe's
own ``description`` when set; a file target prints neither."""

from __future__ import annotations

from pathlib import Path

from rich.markup import escape

from docket import ui
from docket.core import config_docs as _config_docs
from docket.core import pod_apply as _pod_apply


def _target(args: list[str]) -> Path:
    if args and args[0]:
        return Path(args[0])
    default_docket_dir = Path.cwd() / ".docket"
    return default_docket_dir if default_docket_dir.is_dir() else Path.cwd()


def _load_one(
    path: Path,
) -> tuple[_config_docs.Document | None, _config_docs.ConfigDocError | None]:
    try:
        return _config_docs.load_document(path), None
    except _config_docs.ConfigDocError as exc:
        return None, exc


def run_validate(args: list[str]) -> int:
    target = _target(args)
    if not target.exists():
        ui.error(f"Not found: {target}")
        return 1

    paths = [target] if target.is_file() else _config_docs.discover_config_paths(target)
    results = [(path, *_load_one(path)) for path in paths]
    results.sort(key=lambda item: item[2] is None)  # invalid (error is not None) first

    exit_code = 0
    for path, document, error in results:
        if error is not None:
            ui.console.print(f"[red]{escape(str(error))}[/red]")
            exit_code = 1
            continue
        assert document is not None
        if document.deprecated:
            ui.console.print(
                f"note: {path} has no 'kind:' -- add 'kind: {document.kind}' "
                "(files without it stop loading one release after v1)"
            )
        ui.console.print(f"ok {path} ({document.kind} {document.name})")

    if not target.is_file():
        summary = _pod_apply.summarize_recipe(target)
        ui.console.print(f"summary: {summary.render()}")
        if summary.description:
            ui.console.print(escape(summary.description))

    return exit_code
