"""The provider catalog (`models/catalog.py`).

Covers ``load_provider_document`` (the `kind: provider` document loader,
specs/functional/model-profiles.spec.md "Provider catalog") and a structural guarantee: every
built-in provider docket knows is a document under ``templates/providers/``, and no other module
holds a provider-name literal in a table of its own (ADR 0011's "seven tables, seven
populations" problem). That guarantee is checked by an AST scan rather than a fixed provider
list, so it keeps holding as the catalog grows.
"""

from __future__ import annotations

SUBJECT = "docket.models.provider_lifecycle"
