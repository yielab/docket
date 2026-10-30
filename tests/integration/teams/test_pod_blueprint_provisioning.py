"""Pod blueprint provisioning end-to-end.

Covers: every built-in blueprint provisions a real pod; `software` provisions
byte-for-byte identically to the underlying `_pod.build_pod` primitive (a
hard parity requirement); a `workdir` blueprint's pod passes `docket setup --fix`
clean; `docket init --from spec.yaml` provisions a pod via a `blueprint` field
without disturbing the existing single-agent declarative path; an unknown
blueprint fails cleanly in both the interactive and declarative surfaces.

The blueprint *format* itself (registry, validation, pipeline/gate fidelity)
is covered by test_pod_blueprints.py — this file is provisioning I/O only.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from tests.support.pods import build_pod
from tests.support.pods import ids as _ids
from tests.support.pods import meta as _meta
from tests.support.pods import seed_empty_home as _seed

from docket.interfaces.cli.commands import agents as _agents
from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.commands import pod as _pod
from docket.interfaces.cli.commands import setup_check as _setup_check
from docket.kernel.home import Home, current_home
from docket.teams import blueprints as _bp
from docket.teams import member_workspace as _member_workspace
from docket.teams import pod as _pod_core

SUBJECT = "docket.teams.blueprints"

# ── hermetic helpers (mirrors test_pod_roles_from_archetypes.py / test_pod_resources.py) ──


def _ws(home: Path, member_id: str) -> Path:
    return Home(home).projects_dir / member_id


# ── every built-in blueprint provisions ─────────────────────────────────────


class TestBuiltinBlueprintsProvision:
    @pytest.mark.parametrize(
        "blueprint_name,expected_roles",
        [
            ("software", ("lead", "implementer")),
            ("research", ("lead", "researcher", "analyst", "writer", "critic")),
            ("content", ("lead", "writer", "critic")),
            ("ops", ("lead", "operator", "monitor")),
            ("agentic-product", ("lead", "implementer", "reviewer", "tester")),
        ],
    )
    def test_provisions_expected_members_and_files(
        self,
        tmp_path: Path,
        blueprint_name: str,
        expected_roles: tuple[str, ...],
    ) -> None:
        with _seed(tmp_path) as oc_dir:
            blueprint = _bp.get_blueprint(blueprint_name)
            location = "/src/demo" if blueprint.workspace_kind == "codebase" else ""

            created = _pod.build_pod_from_blueprint(
                "demo",
                blueprint_name,
                location=location,
                stack="Python",
                description="the objective",
            )

            expected_ids = [f"demo-{r}" for r in expected_roles]
            assert sorted(created) == sorted(expected_ids)
            assert sorted(_ids(oc_dir)) == sorted(expected_ids)

            for mid in created:
                ws = _ws(oc_dir, mid)
                for f in (
                    "SOUL.md",
                    "AGENTS.md",
                    "HEARTBEAT.md",
                    "WORKFLOW_AUTO.md",
                    "MEMORY.md",
                    ".docket-meta.json",
                ):
                    assert (ws / f).is_file(), f"{mid}: missing {f}"
                assert not list((ws / "memory").glob("*.md")), f"{mid}: a daily log was seeded"

                meta = _meta(oc_dir, mid)
                assert meta["blueprint"] == blueprint_name
                if meta["role"] != "implementer":
                    assert not (ws / "TOOLS.md").exists(), f"{mid}: unexpected TOOLS.md"

                if blueprint.workspace_kind == "workdir":
                    assert meta["workspaceKind"] == "workdir"
                    assert meta["workDir"]
                    assert "## Your working directory" in (ws / "WORKFLOW_AUTO.md").read_text()
                    assert "## Your codebase" not in (ws / "WORKFLOW_AUTO.md").read_text()
                    for name in ("AGENTS.md", "MEMORY.md"):
                        text = (ws / name).read_text().lower()
                        assert "repository map" not in text, f"{mid}: {name}"
                        assert "codebase readme" not in text, f"{mid}: {name}"
                    assert _member_workspace.member_sync_status(mid) is not None
                    assert not _member_workspace.member_sync_status(mid).stale  # type: ignore[union-attr]
                else:
                    assert "workspaceKind" not in meta
                    assert "workDir" not in meta
                    assert "## Your codebase" in (ws / "WORKFLOW_AUTO.md").read_text()

    @pytest.mark.parametrize(
        "blueprint_name,expected_budget",
        [
            ("software", None),
            ("research", 20.0),
            ("content", 15.0),
            ("ops", 30.0),
            ("agentic-product", None),
        ],
    )
    def test_default_budget_applies_to_lead_only(
        self,
        tmp_path: Path,
        blueprint_name: str,
        expected_budget: float | None,
    ) -> None:
        with _seed(tmp_path) as oc_dir:
            blueprint = _bp.get_blueprint(blueprint_name)
            location = "/src/demo" if blueprint.workspace_kind == "codebase" else ""
            created = _pod.build_pod_from_blueprint("demo", blueprint_name, location=location)

            lead_meta = _meta(oc_dir, "demo-lead")
            if expected_budget is None:
                assert "budgetUsd" not in lead_meta
            else:
                assert float(lead_meta["budgetUsd"]) == expected_budget

            for mid in created:
                if mid != "demo-lead":
                    assert "budgetUsd" not in _meta(oc_dir, mid)

    def test_workdir_auto_provisioned_when_location_omitted(self, tmp_path: Path) -> None:
        with _seed(tmp_path) as oc_dir:
            _pod.build_pod_from_blueprint("myops", "ops")
            work_dir = Path(_meta(oc_dir, "myops-lead")["workDir"])
            assert work_dir.is_dir()
            assert work_dir == current_home().pod_work_dir("myops")

    def test_workdir_explicit_location_used_and_created(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            custom = tmp_path / "my-custom-work-dir"
            created = _pod.build_pod_from_blueprint(
                "myresearch", "research", location=str(custom), stack=""
            )
            assert custom.is_dir()
            assert created  # sanity: pod actually provisioned


# ── hard requirement: `software` behaves exactly as it did before blueprints ──


class TestSoftwareParity:
    """Provisions two environments, one via `_pod.build_pod`, one via
    `build_pod_from_blueprint(..., "software", ...)`; every file must match byte-for-byte
    once each tmp-dir root is normalized out (`DOCKET_SCRATCH_DIR` in TOOLS.md)."""

    _MEMBER_FILES = ("SOUL.md", "AGENTS.md", "HEARTBEAT.md", "WORKFLOW_AUTO.md", "MEMORY.md")

    @contextmanager
    def _provision(self, root: Path, *, via_blueprint: bool) -> Iterator[Path]:
        with _seed(root) as oc_dir:
            if via_blueprint:
                _pod.build_pod_from_blueprint(
                    "demo", "software", location="/src/demo", stack="Python", description="the app"
                )
            else:
                build_pod(
                    "demo",
                    _pod_core.DEFAULT_POD_ROLES,
                    codebase="/src/demo",
                    stack="Python",
                    description="the app",
                )
            yield oc_dir

    @staticmethod
    def _normalize_root(text: str, oc_dir: Path) -> str:
        return text.replace(str(oc_dir), "OC_ROOT")

    def test_workspace_files_byte_identical(self, tmp_path: Path) -> None:
        with (
            self._provision(tmp_path / "a", via_blueprint=False) as oc_a,
            self._provision(tmp_path / "b", via_blueprint=True) as oc_b,
        ):
            for role in ("lead", "implementer"):
                ws_a, ws_b = _ws(oc_a, f"demo-{role}"), _ws(oc_b, f"demo-{role}")
                for fname in self._MEMBER_FILES:
                    text_a = self._normalize_root((ws_a / fname).read_text(), oc_a)
                    text_b = self._normalize_root((ws_b / fname).read_text(), oc_b)
                    assert text_a == text_b, f"{role}/{fname} differs"

            # TOOLS.md exists only for the Implementer, in both — same port
            # numbers (both start from an equally empty allocation table).
            assert not (_ws(oc_a, "demo-lead") / "TOOLS.md").exists()
            assert not (_ws(oc_b, "demo-lead") / "TOOLS.md").exists()
            tools_a = self._normalize_root(
                (_ws(oc_a, "demo-implementer") / "TOOLS.md").read_text(), oc_a
            )
            tools_b = self._normalize_root(
                (_ws(oc_b, "demo-implementer") / "TOOLS.md").read_text(), oc_b
            )
            assert tools_a == tools_b

    def test_meta_identical_except_additive_blueprint_stamp(self, tmp_path: Path) -> None:
        with (
            self._provision(tmp_path / "a", via_blueprint=False) as oc_a,
            self._provision(tmp_path / "b", via_blueprint=True) as oc_b,
        ):
            for mid in ("demo-lead", "demo-implementer"):
                meta_a = _meta(oc_a, mid)
                meta_b = _meta(oc_b, mid)
                # Two fields legitimately differ across two separate provisioning
                # calls / tmp-dir roots: the creation timestamp, and (implementer
                # only) the absolute scratch-dir path.
                meta_a.pop("created", None)
                meta_b.pop("created", None)
                if "scratchDir" in meta_a or "scratchDir" in meta_b:
                    assert meta_a.pop("scratchDir", "").endswith("/workspaces/pods/demo/.scratch")
                    assert meta_b.pop("scratchDir", "").endswith("/workspaces/pods/demo/.scratch")
                assert meta_b.pop("blueprint") == "software"
                assert "blueprint" not in meta_a
                assert "workspaceKind" not in meta_a
                assert "workspaceKind" not in meta_b
                assert meta_a == meta_b

    def test_same_member_ids_and_registration(self, tmp_path: Path) -> None:
        with (
            self._provision(tmp_path / "a", via_blueprint=False) as oc_a,
            self._provision(tmp_path / "b", via_blueprint=True) as oc_b,
        ):
            assert sorted(_ids(oc_a)) == sorted(_ids(oc_b)) == ["demo-implementer", "demo-lead"]

    def test_no_default_budget_cap(self, tmp_path: Path) -> None:
        with self._provision(tmp_path / "b", via_blueprint=True) as oc_b:
            assert "budgetUsd" not in _meta(oc_b, "demo-lead")


# ── docket setup accepts a workdir blueprint pod ───────────────────────────


class TestDoctorAcceptsWorkdirBlueprint:
    @pytest.mark.parametrize("blueprint_name", ["research", "content", "ops"])
    def test_pod_passes_doctor_clean(self, tmp_path: Path, blueprint_name: str) -> None:
        with _seed(tmp_path) as oc_dir:
            created = _pod.build_pod_from_blueprint(
                "myproj", blueprint_name, stack="", description="objective"
            )
            issues = _setup_check._check_project_agents(sorted(created))
            assert issues == 0
            del oc_dir  # only used to keep _seed's return value referenced

    def test_software_pod_still_passes_doctor_clean(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            created = _pod.build_pod_from_blueprint("demo", "software", location="/src/demo")
            assert _setup_check._check_project_agents(sorted(created)) == 0

    def test_agentic_product_pod_passes_doctor_clean(self, tmp_path: Path) -> None:
        # codebase-kind, full (lead/implementer/reviewer/tester) roster —
        # same doctor path software's full pod (`--pod full`) already
        # exercises, just reached via a blueprint name.
        with _seed(tmp_path):
            created = _pod.build_pod_from_blueprint(
                "demo", "agentic-product", location="/src/demo", stack="Python"
            )
            assert sorted(r.split("-", 1)[1] for r in created) == [
                "implementer",
                "lead",
                "reviewer",
                "tester",
            ]
            assert _setup_check._check_project_agents(sorted(created)) == 0


# ── unknown blueprint fails cleanly ─────────────────────────────────────────


class TestUnknownBlueprintFailsCleanly:
    def test_build_pod_from_blueprint_raises_blueprint_error(self, tmp_path: Path) -> None:
        with _seed(tmp_path), pytest.raises(_bp.BlueprintError, match="unknown blueprint"):
            _pod.build_pod_from_blueprint("demo", "wizard-pod")

    def test_interactive_add_unknown_blueprint_exits_one_before_any_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_contract, "is_tty", lambda: True)

        def _no_input(_prompt: str = "") -> str:
            raise AssertionError("must fail before prompting for anything")

        monkeypatch.setattr("builtins.input", _no_input)
        rc = _agents.run_init(_agents.InitRequest(name="myproj", blueprint="wizard-pod"))
        assert rc == 1

    def test_from_spec_unknown_blueprint_is_skipped_not_aborted(self, tmp_path: Path) -> None:
        with _seed(tmp_path) as oc_dir:
            good = tmp_path / "goodagent"
            good.mkdir()
            spec = [
                {"id": "bad-pod", "blueprint": "wizard-pod"},
                {"id": "goodagent", "blueprint": "software", "codebase": str(good)},
            ]
            spec_file = tmp_path / "spec.json"
            spec_file.write_text(json.dumps(spec))

            rc = _agents.run_init(_agents.InitRequest(from_file=str(spec_file)))

            assert rc == 0
            ids = _ids(oc_dir)
            assert "goodagent-lead" in ids
            assert not any(i.startswith("bad-pod") for i in ids)


# ── `docket init --from spec.yaml` handles blueprints ────────────────────────


class TestFromSpecBlueprint:
    def test_from_spec_provisions_pod_via_blueprint(self, tmp_path: Path) -> None:
        with _seed(tmp_path) as oc_dir:
            spec = [
                {
                    "id": "myresearch",
                    "blueprint": "research",
                    "workDir": str(tmp_path / "research-work"),
                    "description": "look into X",
                    "budgetUsd": "5",
                }
            ]
            spec_file = tmp_path / "spec.json"
            spec_file.write_text(json.dumps(spec))

            rc = _agents.run_init(_agents.InitRequest(from_file=str(spec_file)))

            assert rc == 0
            ids = _ids(oc_dir)
            for role in ("lead", "researcher", "analyst", "writer", "critic"):
                assert f"myresearch-{role}" in ids

            meta = _meta(oc_dir, "myresearch-lead")
            assert meta["blueprint"] == "research"
            assert meta["workspaceKind"] == "workdir"
            assert meta["workDir"] == str(tmp_path / "research-work")
            # Explicit spec budgetUsd overrides the blueprint's own default (20.0).
            assert float(meta["budgetUsd"]) == 5.0

    def test_from_spec_software_blueprint_matches_codebase_field(self, tmp_path: Path) -> None:
        with _seed(tmp_path) as oc_dir:
            code = tmp_path / "demo"
            code.mkdir()
            spec = {"id": "demo", "blueprint": "software", "codebase": str(code), "stack": "Python"}
            spec_file = tmp_path / "spec.json"
            spec_file.write_text(json.dumps(spec))

            rc = _agents.run_init(_agents.InitRequest(from_file=str(spec_file)))

            assert rc == 0
            assert sorted(_ids(oc_dir)) == ["demo-implementer", "demo-lead"]
            assert _meta(oc_dir, "demo-lead")["codebase"] == str(code)

    def test_from_spec_existing_pod_is_skipped_not_recreated(self, tmp_path: Path) -> None:
        with _seed(tmp_path) as oc_dir:
            code = tmp_path / "demo"
            code.mkdir()
            _pod.build_pod_from_blueprint("demo", "software", location=str(code))
            spec = [{"id": "demo", "blueprint": "software", "codebase": str(code)}]
            spec_file = tmp_path / "spec.json"
            spec_file.write_text(json.dumps(spec))

            rc = _agents.run_init(_agents.InitRequest(from_file=str(spec_file)))

            assert rc == 0
            assert sorted(_ids(oc_dir)) == ["demo-implementer", "demo-lead"]

    def test_from_spec_invalid_project_id_exits_one_and_provisions_nothing(
        self, tmp_path: Path
    ) -> None:
        # An `id` that fails validate_project_id (here: path-traversal
        # characters) must not reach provision_pod's workspace-path
        # construction -- the command exits 1 and nothing is provisioned.
        with _seed(tmp_path) as oc_dir:
            spec = [{"id": "../../escaped", "blueprint": "software", "codebase": "/src/demo"}]
            spec_file = tmp_path / "spec.json"
            spec_file.write_text(json.dumps(spec))

            rc = _agents.run_init(_agents.InitRequest(from_file=str(spec_file)))

            assert rc == 1
            assert _ids(oc_dir) == []
