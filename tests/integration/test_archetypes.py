"""`core/archetypes.py` — the declarative role-archetype registry.

Covers: closed-enum rejection (scope/modelClass/gateContract kind), the built-in and
starter-library archetypes validating, the user-overlay pattern (mirrors `docket-models.json`:
built-ins + starter library overlaid by `~/.docket/docket-roles.json`, user wins by name),
`docket pod roles` list/show and `pod apply <file>`, and that reviewer/tester gate-contract data resolved
through `core.orchestrator` matches `core/pipeline.py`'s own hardcoded `default_pipeline()`
verdict gates -- gate execution is generic, not a cross-check against a dispatch-private regex
constant (see `core/dispatch.py`'s docstring note on `_REVIEWER_VERDICT_RE`/`_TESTER_VERDICT_RE`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.core import archetypes as arch
from docket.core import orchestrator as _orch
from docket.core import pipeline as _pipeline

SUBJECT = "docket.core.archetypes"


@pytest.fixture
def registry_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "docket-roles.json"
    monkeypatch.setattr(_cfg, "ARCHETYPE_REGISTRY_FILE", path, raising=True)
    return path


@pytest.fixture
def seeded_pod() -> str:
    return "demo"


class TestClosedEnums:
    def _base_doc(self, **overrides: object) -> dict[str, object]:
        doc: dict[str, object] = {
            "name": "custom",
            "version": 1,
            "scope": "pod",
            "modelClass": "cheap",
            "soulTemplate": "hello ${project}",
            "agentsTemplate": "hi ${project}",
            "gateContract": {"kind": "none"},
            "toolProfile": "x",
        }
        doc.update(overrides)
        return doc

    def test_unknown_scope_rejected(self) -> None:
        with pytest.raises(arch.ArchetypeError, match="scope"):
            arch.from_wire("custom", self._base_doc(scope="galaxy"))

    def test_unknown_model_class_rejected(self) -> None:
        with pytest.raises(arch.ArchetypeError, match="modelClass"):
            arch.from_wire("custom", self._base_doc(modelClass="medium"))

    def test_unknown_gate_contract_kind_rejected(self) -> None:
        with pytest.raises(arch.ArchetypeError, match="gate contract kind"):
            arch.from_wire("custom", self._base_doc(gateContract={"kind": "vibes"}))

    def test_blank_soul_template_rejected(self) -> None:
        with pytest.raises(arch.ArchetypeError, match="soulTemplate"):
            arch.from_wire("custom", self._base_doc(soulTemplate="   "))

    def test_blank_agents_template_rejected(self) -> None:
        with pytest.raises(arch.ArchetypeError, match="agentsTemplate"):
            arch.from_wire("custom", self._base_doc(agentsTemplate=""))

    def test_invalid_name_rejected(self) -> None:
        with pytest.raises(arch.ArchetypeError, match="invalid archetype name"):
            arch.from_wire("Bad Name!", self._base_doc(name="Bad Name!"))

    def test_non_positive_version_rejected(self) -> None:
        with pytest.raises(arch.ArchetypeError, match="version"):
            arch.from_wire("custom", self._base_doc(version=0))

    def test_bad_gate_regex_rejected(self) -> None:
        with pytest.raises(arch.ArchetypeError, match="does not compile"):
            arch.from_wire(
                "custom",
                self._base_doc(gateContract={"kind": "verdict", "regexes": ["(unbalanced"]}),
            )

    def test_name_mismatch_rejected(self) -> None:
        with pytest.raises(arch.ArchetypeError, match="does not match"):
            arch.from_wire("custom", self._base_doc(name="other"))

    def test_valid_doc_round_trips(self) -> None:
        parsed = arch.from_wire("custom", self._base_doc())
        assert parsed.name == "custom"
        assert parsed.scope == "pod"
        assert parsed.model_class == "cheap"
        back = parsed.to_wire()
        reparsed = arch.from_wire("custom", back)
        assert reparsed == parsed


class TestBuiltinAndStarterArchetypes:
    def test_builtin_role_order(self) -> None:
        assert arch.BUILTIN_ROLE_ORDER == ("lead", "implementer", "reviewer", "tester")

    def test_starter_role_order(self) -> None:
        assert arch.STARTER_ROLE_ORDER == (
            "researcher",
            "analyst",
            "writer",
            "critic",
            "operator",
            "monitor",
        )

    @pytest.mark.parametrize("name", ["lead", "implementer", "reviewer", "tester"])
    def test_builtin_validates(self, name: str) -> None:
        found = arch.BUILTIN_ARCHETYPES[name]
        assert arch.validate_archetype_dict(name, found.to_wire()) == []

    @pytest.mark.parametrize(
        "name", ["researcher", "analyst", "writer", "critic", "operator", "monitor"]
    )
    def test_starter_validates(self, name: str) -> None:
        found = arch.STARTER_ARCHETYPES[name]
        assert arch.validate_archetype_dict(name, found.to_wire()) == []

    def test_every_builtin_and_starter_archetype_has_its_own_policy_row(self) -> None:
        """One vocabulary: an archetype's model row is its own name."""
        from docket.core import models_policy as mp

        names = {*arch.BUILTIN_ARCHETYPES, *arch.STARTER_ARCHETYPES}
        assert set(mp.ROLE_CLASS) == names
        assert set(mp.ALL_ROLES) == names

    def test_reviewer_gate_matches_pipeline_default_verdict_gate(self) -> None:
        """The archetype's `gateContract`, resolved through `core.orchestrator`, must produce
        the same pattern/passValues as `core/pipeline.py`'s hardcoded reviewer step -- two
        independent sources describing the same role must agree."""
        found = arch.BUILTIN_ARCHETYPES["reviewer"]
        assert found.gate_contract.kind == "verdict"
        resolved = _orch._gate_from_contract(found.gate_contract)
        assert isinstance(resolved, _pipeline.VerdictGate)

        spec = _pipeline.default_pipeline()
        reviewer_step = next(s for s in spec.steps if s.id == "reviewer")
        assert isinstance(reviewer_step.gate, _pipeline.VerdictGate)
        assert resolved.pattern == reviewer_step.gate.pattern
        # Both gates are case_sensitive=False (the shared marker convention),
        # so pass_values only need to agree case-insensitively — the two
        # sources are free to spell their own literal casing differently
        # (the archetype's regexes are the marker's canonical, upper-case
        # spelling; the pipeline default's passValues happen to be lowercase).
        assert [v.lower() for v in resolved.pass_values] == [
            v.lower() for v in reviewer_step.gate.pass_values
        ]

    def test_tester_gate_matches_pipeline_default_verdict_gate(self) -> None:
        """See the reviewer test's docstring above."""
        found = arch.BUILTIN_ARCHETYPES["tester"]
        assert found.gate_contract.kind == "verdict"
        resolved = _orch._gate_from_contract(found.gate_contract)
        assert isinstance(resolved, _pipeline.VerdictGate)

        spec = _pipeline.default_pipeline()
        tester_step = next(s for s in spec.steps if s.id == "tester")
        assert isinstance(tester_step.gate, _pipeline.VerdictGate)
        assert resolved.pattern == tester_step.gate.pattern
        assert [v.lower() for v in resolved.pass_values] == [
            v.lower() for v in tester_step.gate.pass_values
        ]

    def test_lead_gate_is_none(self) -> None:
        assert arch.BUILTIN_ARCHETYPES["lead"].gate_contract.kind == "none"

    def test_implementer_gate_is_mechanical(self) -> None:
        assert arch.BUILTIN_ARCHETYPES["implementer"].gate_contract.kind == "mechanical"


class TestRender:
    def test_render_substitutes(self) -> None:
        assert arch.render("hi ${project}", {"project": "demo"}) == "hi demo"

    def test_render_unknown_variable_raises(self) -> None:
        with pytest.raises(arch.ArchetypeError, match="unknown variable"):
            arch.render("hi ${typo}", {"project": "demo"})

    def test_render_ignores_unused_extra_variables(self) -> None:
        assert arch.render("hi ${project}", {"project": "demo", "extra": "y"}) == "hi demo"


class TestRegistryOverlay:
    def test_load_registry_without_overlay_has_ten_roles(self, registry_file: Path) -> None:
        registry = arch.load_registry()
        assert set(registry.role_names()) == set(arch.BUILTIN_ARCHETYPES) | set(
            arch.STARTER_ARCHETYPES
        )
        assert len(registry.role_names()) == 10

    def test_user_archetype_adds_new_role(self, registry_file: Path) -> None:
        doc = {
            "name": "producer",
            "version": 1,
            "scope": "pod",
            "modelClass": "cheap",
            "soulTemplate": "hi ${project}",
            "agentsTemplate": "hi ${project}",
            "gateContract": {"kind": "none"},
            "toolProfile": "x",
            "description": "coordinates content production",
        }
        added = arch.add_user_archetype(doc)
        assert added.name == "producer"

        registry = arch.load_registry()
        assert "producer" in registry
        assert registry.get("producer") is not None
        assert registry.get("producer").description == "coordinates content production"  # type: ignore[union-attr]
        assert registry.source_of("producer") == "user"

    def test_user_archetype_overrides_builtin(self, registry_file: Path) -> None:
        """A user archetype named 'lead' overlays (replaces) the built-in — the same
        'user wins' contract docket-models.json uses for per-role model overrides."""
        doc = {
            "name": "lead",
            "version": 2,
            "scope": "pod",
            "modelClass": "strong",
            "soulTemplate": "custom lead soul for ${project}",
            "agentsTemplate": "custom lead agents for ${project}",
            "gateContract": {"kind": "none"},
            "toolProfile": "coordination",
            "description": "customized lead",
        }
        arch.add_user_archetype(doc)

        registry = arch.load_registry()
        found = registry.get("lead")
        assert found is not None
        assert found.version == 2
        assert found.model_class == "strong"
        assert found.soul_template == "custom lead soul for ${project}"
        assert registry.source_of("lead") == "user"

        # Built-in Python literal itself is untouched (module-level constant).
        assert arch.BUILTIN_ARCHETYPES["lead"].model_class == "cheap"

    def test_malformed_overlay_entry_is_skipped_not_fatal(self, registry_file: Path) -> None:
        registry_file.parent.mkdir(parents=True, exist_ok=True)
        registry_file.write_text(
            json.dumps({"roles": {"broken": {"name": "broken", "scope": "not-a-scope"}}}),
            encoding="utf-8",
        )
        registry = arch.load_registry()
        # Malformed 'broken' entry is silently skipped; built-ins/starters still load.
        assert "broken" not in registry
        assert "lead" in registry

    def test_add_user_archetype_requires_name(self, registry_file: Path) -> None:
        with pytest.raises(arch.ArchetypeError, match="name"):
            arch.add_user_archetype({"version": 1})

    def test_parse_yaml_file(self, tmp_path: Path) -> None:
        p = tmp_path / "producer.yaml"
        p.write_text(
            "name: producer\n"
            "version: 1\n"
            "scope: pod\n"
            "modelClass: cheap\n"
            "toolProfile: x\n"
            "gateContract:\n"
            "  kind: none\n"
            'soulTemplate: "hi ${project}"\n'
            'agentsTemplate: "hi ${project}"\n',
            encoding="utf-8",
        )
        doc = arch.parse_yaml_file(str(p))
        assert doc["name"] == "producer"

    def test_parse_yaml_file_missing(self, tmp_path: Path) -> None:
        with pytest.raises(arch.ArchetypeError, match="not found"):
            arch.parse_yaml_file(str(tmp_path / "nope.yaml"))

    def test_parse_yaml_file_not_a_mapping(self, tmp_path: Path) -> None:
        p = tmp_path / "list.yaml"
        p.write_text("- 1\n- 2\n", encoding="utf-8")
        with pytest.raises(arch.ArchetypeError, match="mapping"):
            arch.parse_yaml_file(str(p))


class TestRolesCli:
    @staticmethod
    def _run(*args: str) -> Any:
        from typer.testing import CliRunner

        from docket.cli import _pod

        return CliRunner().invoke(_pod.pod_app, list(args))

    def test_list_exits_zero(self, registry_file: Path) -> None:
        result = self._run("roles")
        assert result.exit_code == 0
        assert "lead" in result.output
        assert "researcher" in result.output

    def test_show_unknown_fails(self, registry_file: Path) -> None:
        assert self._run("roles", "nonexistent").exit_code == 1

    def test_show_known_prints_definition(self, registry_file: Path) -> None:
        result = self._run("roles", "tester")
        assert result.exit_code == 0
        assert "tester" in result.output
        assert "PASS" in result.output or "regexes" in result.output.lower()

    def test_apply_then_list(self, registry_file: Path, tmp_path: Path, seeded_pod: str) -> None:
        p = tmp_path / "producer.yaml"
        p.write_text(
            "kind: role\n"
            "name: producer\n"
            "version: 1\n"
            "scope: pod\n"
            "modelClass: cheap\n"
            "toolProfile: x\n"
            "gateContract:\n"
            "  kind: none\n"
            'soulTemplate: "hi ${project}"\n'
            'agentsTemplate: "hi ${project}"\n',
            encoding="utf-8",
        )
        assert self._run("apply", str(p), "--pod", seeded_pod).exit_code == 0
        assert "producer" in self._run("roles", "--pod", seeded_pod).output

    def test_apply_rejects_invalid_scope(
        self, registry_file: Path, tmp_path: Path, seeded_pod: str
    ) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text(
            "kind: role\n"
            "name: bad\n"
            "version: 1\n"
            "scope: galaxy\n"
            "modelClass: cheap\n"
            "toolProfile: x\n"
            "gateContract:\n"
            "  kind: none\n"
            'soulTemplate: "hi ${project}"\n'
            'agentsTemplate: "hi ${project}"\n',
            encoding="utf-8",
        )
        assert self._run("apply", str(p), "--pod", seeded_pod).exit_code == 1

    def test_list_rejects_unknown_flag(self, registry_file: Path) -> None:
        """A flag `roles` does not declare is a usage error, never a silently ignored token."""
        assert self._run("roles", "--bogus").exit_code == 2

    def test_list_json_names_each_archetype(self, registry_file: Path) -> None:
        rows = json.loads(self._run("roles", "--json").output)
        assert "lead" in {r["name"] for r in rows}
