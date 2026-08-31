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
    "config.py",
    "core/__init__.py",
    "core/agent_loop.py",
    "core/approval.py",
    "core/archetypes.py",
    "core/audit.py",
    "core/context.py",
    "core/fleet.py",
    "core/handoff.py",
    "core/identity.py",
    "core/llm.py",
    "core/memory.py",
    "core/models.py",
    "core/policy.py",
    "core/runtime_driver.py",
    "core/security.py",
    "core/session.py",
    "core/tools.py",
    "core/trace.py",
    "edges/__init__.py",
    "edges/store.py",
    "edges/adapters/__init__.py",
    "edges/adapters/docket_runtime.py",
    "edges/adapters/fetch.py",
    "edges/adapters/llm.py",
    "edges/adapters/system.py",
    "edges/adapters/toolbox.py",
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
