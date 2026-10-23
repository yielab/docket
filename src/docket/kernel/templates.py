"""Where the templates that ship in the wheel live: read-only, never under the home."""

from __future__ import annotations

from pathlib import Path

# kernel/ sits beside templates/ in the package.
_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

# Built-in `kind: provider`, `kind: exporter` and `kind: channel` documents, the "built-in" scope
# of each catalog (core/provider.py, core/exporter.py, core/channel.py).
PROVIDER_TEMPLATES_DIR = _TEMPLATES / "providers"
EXPORTER_TEMPLATES_DIR = _TEMPLATES / "exporters"
CHANNEL_TEMPLATES_DIR = _TEMPLATES / "channels"


def policy_templates_dir() -> Path:
    return _TEMPLATES / "policies"


def recipes_dir() -> Path:
    """Shipped role, pipeline and policy recipe bundles (`templates/recipes/<name>/`)."""
    return _TEMPLATES / "recipes"


def config_schemas_dir() -> Path:
    """The published config-v1 JSON Schemas, shipped byte-for-byte from `docs/contracts/
    config-v1/`; `core.pod_apply.export_pod` copies them into an export's `.schemas/`."""
    return _TEMPLATES / "schemas"
