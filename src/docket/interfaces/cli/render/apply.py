from __future__ import annotations

from pathlib import Path

from rich.markup import escape

from docket.governance import review as _governance_review
from docket.interfaces.cli.render import ui
from docket.observability import exporter as _exporter
from docket.teams.apply import model as _model
from docket.teams.apply import recipes as _recipes
from docket.teams.apply import review as _review

# -- render helpers shared with init ---------------------------------------------------------


def render_apply_header(project: str, directory: Path, summary: _recipes.RecipeSummary) -> None:
    """Print the apply header: the recipe's description when set, then its derived summary."""
    ui.header("Apply plan", f"{project} <- {directory}")
    if summary.description:
        ui.console.print(escape(summary.description))
    ui.console.print(f"  {escape(summary.render())}")


_RUN_LABELS = {
    "pipeline-step": 'pipeline step "{}"',
    "mcp-server": 'MCP server "{}"',
    "plugin": 'plugin "{}"',
    "allow-commands": "allowed commands",
    "network": "network",
    "role-loosens": 'role "{}"',
    "verify": 'verify command "{}"',
    "gate": 'external gate "{}"',
}


def run_item_label(item: _governance_review.RunItem) -> str:
    """The console label of one run-on-this-machine item."""
    return _RUN_LABELS.get(item.kind, item.kind).format(item.name)


def render_run_items(items: tuple[_governance_review.RunItem, ...]) -> None:
    """Print the numbered ``Runs on this machine`` list, one exact command per item."""
    width = max((len(run_item_label(i)) for i in items), default=0)
    ui.console.print("Runs on this machine")
    for n, item in enumerate(items, 1):
        label = run_item_label(item).ljust(width)
        ui.console.print(f"  {n}. {escape(label)}   {escape(item.runs)}")


def render_review(review: _review.PlanReview) -> None:
    """Print the two groups of a repository's directory: adds, then runs on this machine."""
    if review.adds:
        ui.console.print("Adds to the team")
        width = max(len(kind) for kind, _ in review.adds)
        for kind, name in review.adds:
            ui.console.print(f"  {escape(kind.ljust(width))}   {escape(name)}")
    render_run_items(review.runs)


def _render_items(items: tuple[_model.ApplyItem, ...]) -> None:
    for item in items:
        note = f" ({item.note})" if item.note else ""
        ui.console.print(f"  {escape(f'[{item.action}]')} {item.kind}: {item.name}{escape(note)}")


def render_apply_plan(plan: _model.ApplyPlan) -> None:
    """Print an apply plan one item per line, then one line per named exporter."""
    _render_items(plan.items)
    render_exporter_states(plan.exporters)


def render_exporter_states(names: tuple[str, ...]) -> None:
    """Print each exporter's state and, unless enabled, the command that enables it."""
    if not names:
        return

    catalog = _exporter.load_catalog()
    for name in names:
        spec = catalog.get(name)
        if spec is None:
            continue
        state, missing = _exporter.activation_state(spec, health=None)
        if state == "enabled":
            line = f"exporter {name}: enabled"
        elif state == "needs credential":
            line = (
                f"exporter {name}: needs credential {', '.join(missing)} "
                f"-> docket setup export enable {name}"
            )
        else:
            line = f"exporter {name}: {state} -> docket setup export enable {name}"
        ui.console.print(f"  {escape(line)}")
