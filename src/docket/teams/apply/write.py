from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any

import docket.kernel.templates as _templates
from docket.agent.tools import mcp_tools as _mcp_tools
from docket.governance import policy as _policy
from docket.governance.audit import audit_log
from docket.kernel.home import current_home
from docket.pipeline.application import schedule as _sched
from docket.tasks.application import queue as _queue
from docket.teams import fleet as _fleet
from docket.teams import member_workspace as _member_workspace
from docket.teams import pod
from docket.teams import pod_provisioning as _pp
from docket.teams import pod_settings as _pod_settings
from docket.teams import roles as _arch
from docket.teams.apply.model import ApplyPlan, ApplyResult, PodApplyError
from docket.teams.apply.recipes import _directory_files, _named_pipeline_files, directory_digest


def _dump_yaml_file(path: Path, doc: dict[str, Any], *, schema_header: str = "") -> None:
    """Write *doc* to *path* as YAML, key order preserved. *schema_header* -- when given -- is
    written first, an editor-autocomplete comment pointing at the copied schema copy."""
    try:
        import yaml as _yaml  # type: ignore[import-untyped]
    except ImportError:
        raise PodApplyError("PyYAML not installed -- run: pip install pyyaml") from None
    body = _yaml.safe_dump(doc, sort_keys=False)
    path.write_text(f"{schema_header}{body}" if schema_header else body, encoding="utf-8")


def _schema_header(directory: Path, dest_path: Path, kind: str) -> str:
    """The `# yaml-language-server:` comment line for a file ``export_pod`` writes at
    *dest_path*, pointing at *kind*'s schema copied into ``<directory>/.schemas/``."""
    schema_path = directory / ".schemas" / f"{kind}.schema.json"
    rel = os.path.relpath(schema_path, start=dest_path.parent).replace(os.sep, "/")
    if not rel.startswith("."):
        rel = f"./{rel}"
    return f"# yaml-language-server: $schema={rel}\n"


def _export_roles(project: str, directory: Path) -> None:
    """Write *project*'s own pod-overlay role entries -- never a built-in, starter, or
    global-``user`` one -- as short-form ``roles/<name>.yaml`` (``to_short_role``, the inverse
    of ``normalize_role``) plus its paired ``roles/<name>.md`` instructions file."""
    registry = _arch.load_registry(project)
    names = sorted(n for n in registry.role_names() if registry.source_of(n) == f"pod:{project}")
    if not names:
        return
    roles_dir = directory / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        arch = registry.get(name)
        assert arch is not None  # name came from this same registry's role_names()
        doc, markdown = _arch.to_short_role(arch)
        role_path = roles_dir / f"{name}.yaml"
        _dump_yaml_file(role_path, doc, schema_header=_schema_header(directory, role_path, "role"))
        (roles_dir / f"{name}.md").write_text(markdown, encoding="utf-8")


def _export_policies(project: str, directory: Path) -> None:
    """Write *project*'s own policy directory's files as short-form YAML ``policies/<stem>.yaml``
    (``governance.policy.to_short_policy``, the inverse of ``normalize_policy``) -- never a file from
    the fleet-wide ``$POLICIES_DIR``."""
    src_dir = current_home().pod_config_dir(project) / "policies"
    files = (
        sorted(p for pattern in ("*.json", "*.yaml", "*.yml") for p in src_dir.glob(pattern))
        if src_dir.is_dir()
        else []
    )
    if not files:
        return
    dest_dir = directory / "policies"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        short = _policy.to_short_policy(_policy.read_policy(f))
        policy_path = dest_dir / f"{f.stem}.yaml"
        _dump_yaml_file(
            policy_path, short, schema_header=_schema_header(directory, policy_path, "policy")
        )


def _export_plugins(project: str, directory: Path) -> None:
    """Copy *project*'s own ``config/plugins/`` files byte-for-byte as ``plugins/<name>.py``
    -- never a file from a codebase, since a plugin is only ever applied through this pod's
    own scope."""
    src_dir = current_home().pod_config_dir(project) / "plugins"
    files = sorted(src_dir.glob("*.py")) if src_dir.is_dir() else []
    if not files:
        return
    dest_dir = directory / "plugins"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        (dest_dir / f.name).write_bytes(f.read_bytes())


def _export_named_pipelines(project: str, directory: Path) -> None:
    """Copy *project*'s own ``config/pipelines/`` files byte-for-byte as ``pipelines/<name>``."""
    files = _named_pipeline_files(current_home().pod_config_dir(project))
    if not files:
        return
    dest_dir = directory / "pipelines"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        (dest_dir / f.name).write_bytes(f.read_bytes())


def _export_skills(project: str, directory: Path) -> None:
    """Copy *project*'s own ``config/skills/`` byte-for-byte into ``skills/<name>/`` -- unlike
    a role or policy, a skill is not regenerated, since it carries its own files rather than a
    wire document this module knows how to re-render."""
    src_dir = current_home().pod_config_dir(project) / "skills"
    names = sorted(p.name for p in src_dir.iterdir() if p.is_dir()) if src_dir.is_dir() else []
    if not names:
        return
    dest_root = directory / "skills"
    for name in names:
        src = src_dir / name
        if not (src / "SKILL.md").is_file():
            continue
        dest = dest_root / name
        for rel, data in _directory_files(src):
            file_dest = dest / rel
            file_dest.parent.mkdir(parents=True, exist_ok=True)
            file_dest.write_bytes(data)


def _export_mcp_servers(project: str, directory: Path) -> None:
    """Write *project*'s own pod-scoped servers as ``mcp-servers/<name>.yaml`` documents --
    never a global server."""
    servers = _mcp_tools.load_pod_mcp_servers(project)
    if not servers:
        return
    dest_dir = directory / "mcp-servers"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for server in servers:
        _dump_yaml_file(dest_dir / f"{server.name}.yaml", _mcp_tools.mcp_server_document(server))


def _export_pipeline(project: str, directory: Path) -> None:
    """Copy *project*'s bound pipeline copy (if ``PodSettings.pipeline`` is set) as
    ``pipeline.yaml`` -- the default filename ``apply`` resolves with no explicit
    ``pod.yaml`` ``pipeline`` key."""
    src = pod.bound_pipeline_path(project)
    if not src.is_file():
        return
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pipeline.yaml").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def _export_manifest(project: str, directory: Path) -> None:
    """Write ``pod.yaml`` with ``members``, ``settings`` (every non-default ``PodSettings``
    key), and ``exporters`` (this pod's recorded destinations, ADR 0014 rule 7, when set) --
    never a ``pipeline`` key (see ``_export_pipeline``'s docstring)."""
    roster = _queue.pod_full_roster(project)
    members = [role for role, _mid in sorted(roster.items()) if role != "lead"]

    settings_doc = _pod_settings.PodSettings.load_for(project)
    settings_out: dict[str, Any] = {}
    for key in _pod_settings.PodSettings.KEYS:
        if key in ("pipeline", "prepare", "protects"):
            continue  # top-level, never a `settings` entry (see `_settings_with_top_level`)
        value, source = settings_doc.value_and_source(key, project)
        if source == "set" and value is not None:
            settings_out[key] = value

    manifest: dict[str, Any] = {"kind": "pod", "name": project, "members": members}
    if settings_out:
        manifest["settings"] = settings_out
    if settings_doc.exporters:
        manifest["exporters"] = list(settings_doc.exporters)
    if settings_doc.prepare:
        manifest["prepare"] = settings_doc.prepare
    if settings_doc.protects:
        manifest["protects"] = list(settings_doc.protects)
    pod_path = directory / "pod.yaml"
    _dump_yaml_file(pod_path, manifest, schema_header=_schema_header(directory, pod_path, "pod"))


def _export_schemas(directory: Path) -> None:
    """Copy the four published config-v1 JSON Schemas into ``<directory>/.schemas/`` so every
    exported YAML's `# yaml-language-server:` header resolves without reaching outside the
    export -- ``apply``/``discover_config_paths`` never look under ``.schemas/``."""
    src_dir = _templates.CONFIG_SCHEMAS_DIR
    dest_dir = directory / ".schemas"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for kind in ("role", "pipeline", "policy", "pod"):
        src = src_dir / f"{kind}.schema.json"
        if src.is_file():
            (dest_dir / src.name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def export_pod(project: str, directory: Path) -> None:
    """Write *project*'s own scope into *directory*, the same shape ``apply`` reads back.
    Global scope is never written; the non-empty-*directory* refusal is the CLI's job."""
    if not _pp.pod_member_ids(project):
        raise PodApplyError(f"no pod found for '{project}'")
    directory.mkdir(parents=True, exist_ok=True)
    _export_roles(project, directory)
    _export_policies(project, directory)
    _export_plugins(project, directory)
    _export_named_pipelines(project, directory)
    _export_skills(project, directory)
    _export_mcp_servers(project, directory)
    _export_pipeline(project, directory)
    _export_manifest(project, directory)
    _export_schemas(directory)


def apply(plan: ApplyPlan, channel: str = "") -> ApplyResult:
    """Write every non-``skip`` item in *plan* (role -> policy -> plugin -> skill -> mcp-server -> member -> pipeline
    -> setting order). Audits ``pod.apply`` only on change; records ``configSource``/
    ``configDigest`` every time, all-``skip`` included (see below)."""
    lead_id = pod.member_id(plan.project, "lead")

    for role_write in plan._role_writes:
        _arch.add_user_archetype(role_write.doc, plan.project)

    if plan._policy_writes:
        policies_dir = current_home().pod_config_dir(plan.project) / "policies"
        policies_dir.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            current_home().pods_dir.chmod(0o700)
            policies_dir.parent.parent.chmod(0o700)  # PODS_DIR/<project>
            policies_dir.parent.chmod(0o700)  # pod_config_dir(project)
            policies_dir.chmod(0o700)
        for policy_write in plan._policy_writes:
            dest = policies_dir / policy_write.name
            dest.write_text(policy_write.text, encoding="utf-8")
            dest.chmod(0o600)

    if plan._plugin_writes:
        plugins_dir = current_home().pod_config_dir(plan.project) / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            current_home().pods_dir.chmod(0o700)
            plugins_dir.parent.parent.chmod(0o700)  # PODS_DIR/<project>
            plugins_dir.parent.chmod(0o700)  # pod_config_dir(project)
            plugins_dir.chmod(0o700)
        for plugin_write in plan._plugin_writes:
            dest = plugins_dir / plugin_write.name
            dest.write_bytes(plugin_write.source)
            dest.chmod(0o600)

    if plan._named_pipeline_writes:
        pipelines_dir = current_home().pod_config_dir(plan.project) / "pipelines"
        pipelines_dir.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            current_home().pods_dir.chmod(0o700)
            pipelines_dir.parent.parent.chmod(0o700)  # PODS_DIR/<project>
            pipelines_dir.parent.chmod(0o700)  # pod_config_dir(project)
            pipelines_dir.chmod(0o700)
        for named_write in plan._named_pipeline_writes:
            dest = pipelines_dir / named_write.name
            dest.write_bytes(named_write.source)
            dest.chmod(0o600)

    if plan._skill_writes:
        skills_dir = current_home().pod_config_dir(plan.project) / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            current_home().pods_dir.chmod(0o700)
            skills_dir.parent.parent.chmod(0o700)  # PODS_DIR/<project>
            skills_dir.parent.chmod(0o700)  # pod_config_dir(project)
            skills_dir.chmod(0o700)
        for skill_write in plan._skill_writes:
            dest = skills_dir / skill_write.name
            dest.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(OSError):
                dest.chmod(0o700)
            for rel, data in skill_write.files:
                file_dest = dest / rel
                file_dest.parent.mkdir(parents=True, exist_ok=True)
                file_dest.write_bytes(data)
                file_dest.chmod(0o600)

    if plan._mcp_server_write is not None:
        _mcp_tools.write_pod_mcp_servers(plan.project, list(plan._mcp_server_write.servers))

    for member_write in plan._member_writes:
        ok, msg = _member_workspace.provision_member(
            member_write.member,
            codebase=member_write.codebase,
            stack=member_write.stack,
            description=member_write.description,
            project=plan.project,
            project_key=member_write.project_key,
            work_dir=member_write.work_dir,
            blueprint_name=member_write.blueprint_name,
        )
        if not ok:
            raise PodApplyError(f"failed to provision {member_write.member.member_id}: {msg}")

    if plan._pipeline_write is not None:
        dest = pod.bound_pipeline_path(plan.project)
        dest.write_text(plan._pipeline_write.text, encoding="utf-8")
        dest.chmod(0o600)
        _fleet.meta_set(lead_id, "pipeline", plan._pipeline_write.digest)

    for setting_write in plan._setting_writes:
        if setting_write.key == "schedule":
            _sched.set_schedule(
                current_home().schedule_file, plan.project, str(setting_write.value)
            )
        _fleet.meta_set(lead_id, setting_write.key, setting_write.value)

    if plan.has_changes():
        summary = ";".join(f"{item.kind}:{item.name}:{item.action}" for item in plan.items)
        via = f" channel={channel}" if channel else ""
        audit_log("pod.apply", f"project={plan.project} dir={plan.directory} items={summary}{via}")

    # The configuration-of-record (ADR 0012 §2 rule 5): recorded after every plan
    # `plan_apply` validated, an all-`skip` plan included, so composing a second, identical
    # directory at another path still moves the record -- never by `docket pod set`
    # (see `pod.PodSettings.RECORDED_KEYS`). The audit entry above keeps its own,
    # narrower "only when something changed" rule.
    _fleet.meta_set(lead_id, "configSource", str(plan.directory.resolve()))
    _fleet.meta_set(lead_id, "configDigest", directory_digest(plan.directory))

    # Recorded the same way, every apply, `exporters` included -- never merged with what a
    # prior apply named: an empty list here clears a previous recipe's destinations, matching
    # `configSource`/`configDigest` always describing the *last* directory applied (ADR 0014
    # rule 7). Activates nothing: no write ever reaches `docket-exporters.json` from this path.
    _fleet.meta_set(lead_id, "exporters", ",".join(plan.exporters))

    return ApplyResult(project=plan.project, items=plan.items, exporters=plan.exporters)
