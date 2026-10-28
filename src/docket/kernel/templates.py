"""Where the templates that ship in the wheel live: read-only, never under the home."""

from __future__ import annotations

from pathlib import Path

# kernel/ sits beside templates/ in the package.
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# Built-in `kind: provider`, `kind: exporter` and `kind: channel` documents, the "built-in" scope
# of each catalog (models/catalog.py, observability/exporter.py, operator/channel.py).
PROVIDER_TEMPLATES_DIR = TEMPLATES_DIR / "providers"
EXPORTER_TEMPLATES_DIR = TEMPLATES_DIR / "exporters"
CHANNEL_TEMPLATES_DIR = TEMPLATES_DIR / "channels"
POLICY_TEMPLATES_DIR = TEMPLATES_DIR / "policies"
# The built-in `kind: autonomy` document: the table of what a pause does at each autonomy level.
AUTONOMY_TEMPLATES_DIR = TEMPLATES_DIR / "autonomy"
# The shipped `kind: prompt` files (`prompts/{identity,hop}/<name>.md`): the built-in roles' soul
# templates and hop instructions, read by `teams/prompts.py`.
PROMPT_TEMPLATES_DIR = TEMPLATES_DIR / "prompts"
# Shipped role, pipeline and policy recipe bundles (`templates/recipes/<name>/`).
RECIPES_DIR = TEMPLATES_DIR / "recipes"
# The published config-v1 JSON Schemas, shipped byte-for-byte from `docs/contracts/config-v1/`;
# `teams.apply.plan.export_pod` copies them into an export's `.schemas/`.
CONFIG_SCHEMAS_DIR = TEMPLATES_DIR / "schemas"
