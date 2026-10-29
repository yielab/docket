"""The prompt manifest of a hop: which prompts its turn was composed from, by identity and hash.

``HopResult.prompt_manifest`` (``tasks/domain/task.py``) holds what :func:`build_manifest`
returns: one entry per prompt layer (``identity``, then ``task`` when the hop's message has a
``## Task`` section, then ``hop``), and the model the hop ran on with its provider, class and
profile. The
hash is the prompt's own (``LoadedPrompt.sha256``), so a reader can compare it with the file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from docket.agent import ports as _rd
from docket.kernel.handoff import HANDOFF_SCHEMA
from docket.models.application.endpoint import resolve_profile
from docket.teams import prompts as _prompts


@dataclass(frozen=True)
class Layer:
    """One layer of a hop's composition: its name (``identity``, ``task``, ``hop``) and its prompt."""

    layer: str
    prompt: _prompts.LoadedPrompt


def identity_layer(role: str, project: str) -> Layer | None:
    """The *role*'s identity prompt as the hop's identity layer, or ``None`` when no scope holds
    one (a custom role's identity is its own authored text)."""
    try:
        return Layer("identity", _prompts.resolve_prompt("identity", role, project=project))
    except _prompts.PromptError:
        return None


def build_manifest(layers: list[Layer], model: str) -> dict[str, Any]:
    """The manifest of a hop that ran *model* with *layers*: per layer ``{layer, name, version,
    sha256, scope, tokens}`` (an estimate, never a measurement), then ``model``, ``family``,
    ``class`` and ``profile``."""
    hop = next((entry.prompt for entry in layers if entry.layer == "hop"), None)
    return {
        "layers": [
            {
                "layer": entry.layer,
                "name": entry.prompt.name,
                "version": entry.prompt.version,
                "sha256": entry.prompt.sha256,
                "scope": entry.prompt.scope,
                "tokens": _rd.estimate_tokens(entry.prompt.text),
            }
            for entry in layers
        ],
        "model": model,
        "family": model.partition("/")[0] if "/" in model else "",
        "class": hop.model_class if hop is not None else "any",
        "profile": resolve_profile(model).name,
    }


def offers_handoff(layers: list[Layer]) -> bool:
    """Whether a layer's prompt declares ``output: handoff/v1``: the hop is offered ``handoff``."""
    return any(entry.prompt.output == HANDOFF_SCHEMA for entry in layers)
