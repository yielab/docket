"""Build the private runtime implementation without claiming ``docket`` files.

The control-plane wheel owns ``docket``. At build time this hook copies the
measured runtime closure into ``docket_runtime._internal.docket`` and rewrites
its absolute first-party imports. The same source material is included in the
sdist, so a wheel rebuilt from an sdist has no dependency on the monorepo's
parent directory.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

_RUNTIME_FILES = (
    "__init__.py",
    "agent/__init__.py",
    "agent/handoff.py",
    "agent/llm.py",
    "agent/ports.py",
    "agent/skills.py",
    "agent/tools/__init__.py",
    "agent/tools/builtins/__init__.py",
    "agent/tools/builtins/toolbox.py",
    "agent/tools/registry.py",
    "governance/__init__.py",
    "governance/approval.py",
    "governance/audit.py",
    "governance/plugin_api.py",
    "governance/plugins.py",
    "governance/policy.py",
    "governance/security.py",
    "hops/__init__.py",
    "hops/workspace/__init__.py",
    "hops/workspace/repo_view.py",
    "models/__init__.py",
    "models/catalog.py",
    "models/document_fields.py",
    "observability/__init__.py",
    "observability/trace.py",
    "operator/__init__.py",
    "operator/contract.py",
    "platform/__init__.py",
    "platform/git.py",
    "platform/process.py",
    "platform/store.py",
    "sandbox/__init__.py",
    "sandbox/docker.py",
    "sandbox/landlock.py",
    "sandbox/launch.py",
    "sandbox/seatbelt.py",
    "tasks/__init__.py",
    "tasks/application/__init__.py",
    "tasks/application/consult.py",
    "teams/__init__.py",
    "teams/fleet.py",
    "teams/models.py",
    "kernel/__init__.py",
    "kernel/clock.py",
    "kernel/errors.py",
    "kernel/home.py",
    "kernel/ids.py",
    "kernel/templates.py",
    "kernel/text.py",
    "kernel/threads.py",
)


class CustomBuildHook(BuildHookInterface):
    """Stage the namespace-private implementation for a wheel build."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        if self.target_name != "wheel":
            return

        root = Path(self.root)
        source = root / "runtime-source" / "docket"
        if not source.is_dir():
            source = root.parents[1] / "src" / "docket"

        staged = Path(
            tempfile.mkdtemp(
                prefix="docket-runtime-build-", dir=os.environ.get("DOCKET_RUNTIME_BUILD_TMPDIR")
            )
        )
        package = staged / "docket_runtime" / "_internal" / "docket"
        for relative in _RUNTIME_FILES:
            original = source / relative
            if not original.is_file():
                raise FileNotFoundError(f"Runtime source file missing: {original}")
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                original.read_text(encoding="utf-8").replace(
                    "docket.", "docket_runtime._internal.docket."
                ),
                encoding="utf-8",
            )

        internal = package.parent
        (internal / "__init__.py").write_text('"""Private implementation."""\n')
        force_include = build_data.setdefault("force_include", {})
        if not isinstance(force_include, dict):
            raise TypeError("Hatch build data force_include must be a mapping")
        force_include[str(staged / "docket_runtime" / "_internal")] = "docket_runtime/_internal"

    def finalize(self, version: str, build_data: dict[str, object], artifact_path: str) -> None:
        force_include = build_data.get("force_include", {})
        if not isinstance(force_include, dict):
            return
        for path in force_include:
            staged = Path(path).parents[1]
            if staged.name.startswith("docket-runtime-build-"):
                shutil.rmtree(staged, ignore_errors=True)
