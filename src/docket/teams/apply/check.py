"""What ``docket pod update`` and ``docket pod validate`` check beyond each file's own kind: that
every reference a directory makes resolves, and that every input a prompt declares is one its
layer's consumer supplies (config-format.spec.md, "`docket pod validate`" requirement 5).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from docket.pipeline.domain import spec as _pipeline
from docket.teams import config_docs as _config_docs
from docket.teams import mcp_servers as _mcp_servers
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


# A role's view for the read/act rule: its `tools` allow-list and its `deniedTools`.
RoleTools = tuple[tuple[str, ...], tuple[str, ...]]

SEND_RULE = (
    "a role that acts outside the machine holds no read tool: narrow its tools, "
    "or give every step that runs it a narrower tools list"
)


def _server_of(entry: str) -> str | None:
    """The server an MCP allow-list entry names (`mcp__<server>` or `mcp__<server>__<tool>`)."""
    if not entry.startswith(_roles.MCP_TOOL_PREFIX):
        return None
    return entry[len(_roles.MCP_TOOL_PREFIX) :].split("__", 1)[0]


def _send_and_read(
    tools: Sequence[str], denied: Sequence[str], kinds: Mapping[str, str]
) -> tuple[list[str], list[str]]:
    """The send tools and the read tools (`fetch`, a `read` server's) an allow-list names."""
    sends: list[str] = []
    reads: list[str] = []
    for entry in dict.fromkeys(tools):
        server = _server_of(entry)
        if server is None:
            if entry == "fetch" and entry not in denied:
                reads.append(entry)
            continue
        kind = kinds.get(server)
        if kind == "send":
            sends.append(entry)
        elif kind == "read" and "read" not in denied:
            reads.append(entry)
    return sends, reads


def send_conflicts(
    roles: Mapping[str, RoleTools],
    kinds: Mapping[str, str],
    steps: Mapping[str, Sequence[tuple[str, ...] | None]],
) -> list[str]:
    """One line per role whose `tools` name a `send` tool and that still holds `fetch` or a `read`
    server's tool. *kinds* is server to kind; *steps* is role to each running step's `tools`
    (`None` when it declares none); steps that all narrow the role satisfy the rule."""
    problems: list[str] = []
    for name, (tools, denied) in sorted(roles.items()):
        sends, reads = _send_and_read(tools, denied, kinds)
        if not sends or not reads:
            continue
        views = steps.get(name, ())
        if views and all(view is not None for view in views):
            still = [v for v in views if v is not None and all(_send_and_read(v, denied, kinds))]
            if not still:
                continue
            sends, reads = _send_and_read(still[0], denied, kinds)
            where = "a step's tools"
        else:
            where = "its tools"
        problems.append(
            f"role {name!r}: {where} name the send tool {', '.join(sends)} and the role still "
            f"holds {', '.join(reads)}; {SEND_RULE}"
        )
    return problems


def _directory_server_kinds(directory: Path) -> dict[str, str]:
    kinds: dict[str, str] = {}
    for pattern in ("*.yaml", "*.yml", "*.json"):
        for path in sorted((directory / "mcp-servers").glob(pattern)):
            try:
                config = _mcp_servers.load_mcp_server_document(path)
            except _mcp_servers.McpServerDocError:
                continue  # the kind validator reports it
            kinds[config.name] = config.kind
    return kinds


def _directory_step_tools(directory: Path) -> dict[str, list[tuple[str, ...] | None]]:
    """The `tools` of each step, by the role it runs, over the directory's pipelines."""
    files = [directory / f"pipeline.{ext}" for ext in ("yaml", "yml")]
    files += sorted((directory / "pipelines").glob("*.y*ml"))
    steps: dict[str, list[tuple[str, ...] | None]] = {}
    for path in files:
        if not path.is_file():
            continue
        spec = _pipeline.load_pipeline(path.read_text(encoding="utf-8")).spec
        if spec is None:
            continue
        for step in spec.steps:
            for unit in step.parallel or [step]:
                role = unit.role or unit.archetype
                if role:
                    tools = tuple(unit.tools) if unit.tools is not None else None
                    steps.setdefault(role, []).append(tools)
    return steps


def _role_tools(doc: Mapping[str, object]) -> RoleTools:
    arch = _role_schema.from_wire(str(doc["name"]), dict(doc))
    return tuple(arch.tools or ()), tuple(arch.denied_tools)


def directory_send_problems(directory: Path, project: str) -> list[str]:
    """`send_conflicts` over the roles *directory* declares, with servers read from its
    `mcp-servers/` documents, then *project*'s catalog and the global one."""
    kinds: dict[str, str] = {s.name: s.kind for s in _mcp_servers.load_mcp_servers(project)}
    kinds.update(_directory_server_kinds(directory))
    roles: dict[str, RoleTools] = {}
    for path in _roles.role_files(directory / "roles"):
        try:
            doc = _roles.load_role_file(str(path))
            roles[str(doc["name"])] = _role_tools(doc)
        except _role_schema.ArchetypeError:
            continue  # the kind validator reports it
    return send_conflicts(roles, kinds, _directory_step_tools(directory))


def role_file_send_problems(path: Path, project: str) -> list[str]:
    """`send_conflicts` for one role file under a `roles/` directory, against the servers beside
    it, then *project*'s catalog and the global one."""
    try:
        doc = _roles.load_role_file(str(path))
        roles = {str(doc["name"]): _role_tools(doc)}
    except _role_schema.ArchetypeError:
        return []  # the kind validator reports it
    kinds: dict[str, str] = {s.name: s.kind for s in _mcp_servers.load_mcp_servers(project)}
    kinds.update(_directory_server_kinds(path.parent.parent))
    return send_conflicts(roles, kinds, {})


def directory_problems(directory: Path, project: str, members: object) -> list[str]:
    """Every unresolved reference, unsupplied input and read/act conflict of *directory*, for
    `pod validate`. *members* is the manifest's own list; roles resolve against *directory*'s and
    *project*'s."""
    versions = {name: a.version for name, a in _roles.load_registry(project).items()}
    versions.update(directory_role_versions(directory))
    return [
        *unresolved_members(members, versions),
        *unsupplied_inputs(directory),
        *directory_send_problems(directory, project),
    ]
