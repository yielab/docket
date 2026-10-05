"""``docket.cli._recipes`` -- the BRINGS label and the JSON row, from a real recipe summary."""

from __future__ import annotations

from docket.cli import _recipes
from docket.core import pod_apply as _pod_apply

SUBJECT = "docket.cli._recipes"


def _summary(**overrides: object) -> _pod_apply.RecipeSummary:
    fields: dict[str, object] = {
        "roles": 0,
        "policies": 0,
        "plugins": 0,
        "skills": 0,
        "members": 0,
        "settings": 0,
        "pipeline": "",
        "description": "",
    }
    fields.update(overrides)
    return _pod_apply.RecipeSummary(**fields)  # type: ignore[arg-type]


def test_brings_joins_only_the_parts_present() -> None:
    assert _recipes._brings(_summary()) == "nothing"
    assert _recipes._brings(_summary(roles=2, mcp_servers=("a",))) == "roles+mcp-servers"


def test_the_json_row_names_the_servers_that_run_unjailed() -> None:
    row = _recipes._info_dict(
        "code-intel",
        "shipped",
        "/r",
        _summary(mcp_servers=("ast-grep", "lsp"), unjailed_mcp_servers=("ast-grep",)),
    )
    assert row["mcp_servers"] == ["ast-grep", "lsp"]
    assert row["unjailed_mcp_servers"] == ["ast-grep"]


def test_the_shipped_code_intel_recipe_declares_ast_grep_unjailed() -> None:
    summary = _pod_apply.summarize_recipe(_pod_apply.resolve_recipe("code-intel"))
    assert _recipes._info_dict("code-intel", "shipped", "", summary)["unjailed_mcp_servers"] == [
        "ast-grep"
    ]
