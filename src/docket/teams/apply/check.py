"""What ``docket pod update`` and ``docket pod validate`` check beyond each file's own kind: that
every reference a directory makes resolves, and that every input a prompt declares is one its
layer's consumer supplies (config-format.spec.md, "`docket pod validate`" requirement 5).
"""

from __future__ import annotations

from pathlib import Path

from docket.teams import config_docs as _config_docs
from docket.teams import prompts as _prompts
from docket.teams import role_schema as _role_schema
from docket.teams import roles as _roles


def directory_role_versions(directory: Path) -> dict[str, int]:
    """The version of each role file under *directory*'s ``roles/`` that parses."""
    versions: dict[str, int] = {}
    for path in _roles.role_files(directory / "roles"):
        try:
            doc = _roles.load_role_file(str(path))
            versions[str(doc["name"])] = _role_schema.from_wire(str(doc["name"]), doc).version
        except _role_schema.ArchetypeError:
            continue
    return versions


def unresolved_members(members: object, versions: dict[str, int]) -> list[str]:
    """One line per `members` entry that is not a reference *versions* (role name to version)
    satisfies: an unknown role, or a role whose version is not the major named."""
    if not isinstance(members, list):
        return []
    problems: list[str] = []
    for entry in members:
        if not isinstance(entry, str):
            continue
        try:
            reference = _prompts.parse_reference(entry)
        except _prompts.PromptError:
            continue  # a plain role name the registry check names
        if reference.kind != "role" or reference.major is None:
            continue
        if versions.get(reference.name) != reference.major:
            problems.append(f"{reference}: no role {reference.name} of major {reference.major}")
    return problems


def member_names(members: list[object]) -> list[str]:
    """Each `members` entry as a role name: a reference (`implementer@2`) names its role."""
    names: list[str] = []
    for entry in members:
        try:
            reference = _prompts.parse_reference(str(entry))
        except _prompts.PromptError:
            names.append(str(entry))
        else:
            names.append(reference.name if reference.kind == "role" else str(entry))
    return names


def unsupplied_inputs(directory: Path) -> list[str]:
    """One line per input a prompt under *directory* declares that its layer's consumer does not
    supply; a prompt that does not parse is the kind validator's to report."""
    problems: list[str] = []
    for path in _config_docs.prompt_files(directory):
        try:
            prompt = _prompts.load_prompt_file(path)
        except _prompts.PromptError:
            continue
        supplied = _prompts.SUPPLIED_INPUTS.get(prompt.layer, frozenset())
        problems.extend(
            f"{path}: input {name!r} is not supplied to a {prompt.layer} prompt"
            for name in sorted(set(prompt.inputs) - supplied)
        )
    return problems


def directory_problems(directory: Path, project: str, members: object) -> list[str]:
    """Every unresolved reference and unsupplied input of *directory*, for `pod validate`.
    *members* is the manifest's own list; roles resolve against *directory*'s and *project*'s."""
    versions = {name: a.version for name, a in _roles.load_registry(project).items()}
    versions.update(directory_role_versions(directory))
    return [*unresolved_members(members, versions), *unsupplied_inputs(directory)]
