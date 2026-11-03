"""The gated tool registry, its chokepoint, and the built-in tools (`agent/tools/registry.py`).

Pins the argument-aware command classifier (`git push origin production`
reads as a deploy, not a benign `git`), that a source-tree walk finds
exactly one path to tool execution through `dispatch_tool`, and that
containment holds at the handler as well as at the chokepoint.
"""

from __future__ import annotations

import dataclasses
import json
import urllib.parse
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import pytest
from tests.support import home as _support_home
from tests.support import llm as _support_llm
from tests.support import pods as _support_pods
from tests.support.cli import call as _call
from tests.support.prose import sentence_count

from docket.agent.ports import ToolCall
from docket.agent.tools.builtins import toolbox
from docket.agent.tools.registry import (
    ToolContext,
    ToolRegistry,
    dispatch_tool,
)
from docket.governance import audit as _audit
from docket.governance import secrets as _secrets
from docket.hops.application import builtin_tools
from docket.hops.application.builtin_tools import builtin_registry
from docket.kernel.clock import use_clock
from docket.kernel.home import current_home, use_home
from docket.kernel.tool_outcome import ToolOutcome
from docket.platform import fetch as _fetch
from docket.platform import store as _store
from docket.teams import pod as _pod
from docket.teams.role_composer import registry_for_role

_isolate_gates = _support_home.isolate_gates
workspace = _support_pods.workspace_with_files
ctx = _support_llm.ctx_in_workspace

SUBJECT = "docket.hops.application.builtin_tools"


class TestRegistry:
    @pytest.fixture(autouse=True)
    def _fetch_allowlisted(self) -> Iterator[None]:
        """`fetch` is offered only with an allowlist (agent-loop requirement 83); these tests
        describe the full built-in set."""
        with use_home(
            dataclasses.replace(current_home(), fetch_allowed_domains=("api.example.test",))
        ):
            yield

    def test_builtins_present(self) -> None:
        assert builtin_registry().names() == [
            "bash",
            "consult",
            "edit",
            "fetch",
            "glob",
            "grep",
            "process_output",
            "process_stop",
            "read",
            "skill",
            "write",
        ]

    def test_specs_carry_schemas_the_model_can_use(self) -> None:
        specs = {s.name: s for s in builtin_registry().specs()}
        assert specs["bash"].parameters["required"] == ["command"]
        assert specs["read"].description

    def test_without_narrows_the_set(self) -> None:
        readonly = builtin_registry().without("write", "edit", "bash")
        assert "write" not in readonly and "read" in readonly
        assert len(readonly) == 8

    def test_a_narrowed_registry_denies_the_removed_tool(self, ctx: ToolContext) -> None:
        readonly = builtin_registry().without("write")
        res = dispatch_tool(_call("write", '{"path":"x","content":"y"}'), ctx, readonly)
        assert res.denied and not (ctx.roots[0] / "x").exists()


class TestBashDescriptionPrefersTheFileTools:
    """The bash schema description steers file changes to write/edit."""

    def test_description_names_write_and_edit_over_heredocs(self) -> None:
        tool = builtin_tools.builtin_registry().get("bash")

        assert tool is not None
        assert "`write`/`edit`" in tool.description
        assert "heredocs" in tool.description


class TestConsultDescriptionTellsTheTruth:
    """The consult schema matches its handler and the description says what asking does."""

    def _description(
        self, remaining: int, parks: bool, decides: bool = False, waits: bool = False
    ) -> str:
        registry = builtin_registry()
        builtin_tools.describe_consult(
            registry, remaining=remaining, parks=parks, decides=decides, waits=waits
        )
        tool = registry.get("consult")
        assert tool is not None
        return tool.description

    def test_schema_takes_one_to_five_questions_each_requiring_what_the_handler_requires(
        self,
    ) -> None:
        schema = {s.name: s for s in builtin_registry().specs()}["consult"].parameters

        assert schema["required"] == ["questions"]
        assert list(schema["properties"]) == ["questions"]
        questions = schema["properties"]["questions"]
        assert (questions["minItems"], questions["maxItems"]) == (1, 5)
        assert questions["items"]["required"] == ["kind", "message", "options", "recommendation"]

    def test_the_description_says_an_option_is_one_action_and_questions_are_separate(self) -> None:
        text = self._description(remaining=3, parks=True)

        assert "An option is ONE action" in text
        assert "separate questions" in text
        assert "up to five" in text

    def test_the_default_description_says_asking_ends_the_turn(self) -> None:
        tool = builtin_registry().get("consult")

        assert tool is not None
        assert "ENDS your turn" in tool.description
        assert "decide" in tool.description
        assert "no answer" not in tool.description

    def test_a_dispatch_hop_states_the_consultations_left(self) -> None:
        text = self._description(remaining=2, parks=True)

        assert "ENDS your turn" in text
        assert "2 consultations left" in text

    def test_one_left_is_singular_and_none_left_says_so(self) -> None:
        assert "1 consultation left" in self._description(remaining=1, parks=True)
        assert "no consultations left" in self._description(remaining=0, parks=True)

    def test_outside_dispatch_the_call_returns_no_answer_at_once(self) -> None:
        text = self._description(remaining=3, parks=False)

        assert "ENDS your turn" not in text
        assert "no answer; decide yourself" in text

    def test_a_pod_that_decides_says_the_recommendation_applies_at_once(self) -> None:
        text = self._description(remaining=2, parks=True, decides=True)

        assert "ENDS your turn" not in text
        assert "no answer; decide yourself" not in text
        assert "returns at once with your recommendation applied" in text
        assert "prefer deciding in your reply without the tool" in text
        assert "2 consultations left" in text

    def test_deciding_only_applies_where_the_hop_would_park(self) -> None:
        text = self._description(remaining=3, parks=False, decides=True)

        assert "no answer; decide yourself" in text
        assert "recommendation applied" not in text

    def test_a_hop_that_waits_for_the_terminal_says_the_answer_comes_back_in_the_turn(self) -> None:
        text = self._description(remaining=2, parks=True, waits=True)

        assert "ENDS your turn" not in text
        assert "waits for the person at this terminal" in text
        assert "2 consultations left" in text

    def test_deciding_beats_waiting(self) -> None:
        text = self._description(remaining=2, parks=True, decides=True, waits=True)

        assert "returns at once with your recommendation applied" in text

    def test_the_four_effects_are_distinct(self) -> None:
        parks = self._description(remaining=3, parks=True)
        refuses = self._description(remaining=3, parks=False)
        decides = self._description(remaining=3, parks=True, decides=True)
        waits = self._description(remaining=3, parks=True, waits=True)

        assert len({parks, refuses, decides, waits}) == 4


class TestBashStatesItsRules:
    """The `bash` description names what runs unattended and what asks, from the turn's gate."""

    @staticmethod
    def _stated(**context: object) -> str:
        registry = builtin_registry()
        builtin_tools.state_bash_rules(registry, ToolContext(**context))  # type: ignore[arg-type]
        tool = registry.get("bash")
        assert tool is not None
        return tool.description

    def test_the_built_in_description_lists_the_allowlist_and_the_asking_classes(self) -> None:
        tool = builtin_registry().get("bash")

        assert tool is not None
        stated = tool.description
        assert "Runs without approval: " in stated and "Needs approval: " in stated
        for name in ("git", "pytest", "python3", "rg"):
            assert f" {name}," in stated
        for rule in ("`sed -i`", "`find -exec`", "`$(`", "backticks", "outside the workspace"):
            assert rule in stated

    def test_it_says_every_call_starts_at_the_workspace_root(self) -> None:
        for stated in (self._stated(), self._stated(sandbox="auto")):
            assert "Each call is a new shell that starts at the workspace root" in stated
            assert "give paths relative to it" in stated

    def test_a_pods_extra_bins_join_the_list(self) -> None:
        stated = self._stated(allow_commands=("tox", "uv"))

        assert "tox" in stated and "uv" in stated

    def test_a_long_extra_list_is_cut(self) -> None:
        stated = self._stated(allow_commands=tuple(f"tool{i:02d}" for i in range(40)))

        assert "tool00" in stated and "tool39" not in stated and "..." in stated

    def test_a_jailed_turn_is_told_every_program_runs(self) -> None:
        stated = self._stated(sandbox="auto")

        assert "any program" in stated and "Needs approval: " in stated
        assert "pytest," not in stated

    def test_a_bash_the_caller_made_is_left_alone(self) -> None:
        registry = builtin_registry()
        custom = dataclasses.replace(registry.get("bash"), description="mine")  # type: ignore[type-var]
        registry.register(custom)

        builtin_tools.state_bash_rules(registry, ToolContext(allow_commands=("tox",)))

        tool = registry.get("bash")
        assert tool is not None and tool.description == "mine"


class _FixedClock:
    """A monotonic clock that reads one value."""

    def __init__(self, monotonic: float) -> None:
        self._monotonic = monotonic

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return self._monotonic


class TestBashRunsWithinTheTurnsClock:
    """`bash` never runs past the turn's deadline, and says so when the clamp killed it."""

    @staticmethod
    def _bash(
        monkeypatch: pytest.MonkeyPatch,
        workspace: object,
        *,
        deadline: float | None,
        now: float,
        timeout: int,
        outcome: ToolOutcome,
    ) -> tuple[list[int], ToolOutcome]:
        seen: list[int] = []

        def _record(roots: object, command: str, run_for: int, *rest: object) -> ToolOutcome:
            seen.append(run_for)
            return outcome

        monkeypatch.setattr(toolbox, "run_bash", _record)
        tool = builtin_registry().get("bash")
        assert tool is not None
        context = ToolContext(roots=(workspace,), timeout=120, deadline=deadline)  # type: ignore[arg-type]
        with use_clock(_FixedClock(now)):
            result = tool.handler({"command": "sleep 900", "timeout": timeout}, context)
        return seen, result

    def test_a_request_past_the_deadline_runs_for_the_time_left(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        seen, _ = self._bash(
            monkeypatch,
            tmp_path,
            deadline=1300.0,
            now=1250.0,
            timeout=900,
            outcome=ToolOutcome(True, content="done"),
        )

        assert seen == [50]

    def test_a_killed_result_carries_the_marker(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        _, result = self._bash(
            monkeypatch,
            tmp_path,
            deadline=1300.0,
            now=1250.0,
            timeout=900,
            outcome=ToolOutcome(False, error="command timed out after 50s"),
        )

        assert result.error.endswith(
            "[killed at the turn's remaining time (50 s); run it as a verify gate or raise "
            "turnTimeoutS]"
        )

    def test_a_request_inside_the_time_left_is_not_clamped_or_marked(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        seen, result = self._bash(
            monkeypatch,
            tmp_path,
            deadline=1300.0,
            now=1250.0,
            timeout=20,
            outcome=ToolOutcome(False, error="command timed out after 20s"),
        )

        assert seen == [20] and result.error == "command timed out after 20s"

    def test_a_spent_deadline_still_grants_one_second(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        seen, _ = self._bash(
            monkeypatch,
            tmp_path,
            deadline=1300.0,
            now=1400.0,
            timeout=900,
            outcome=ToolOutcome(True, content="done"),
        )

        assert seen == [1]

    def test_no_deadline_applies_no_clamp(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        seen, _ = self._bash(
            monkeypatch,
            tmp_path,
            deadline=None,
            now=1250.0,
            timeout=900,
            outcome=ToolOutcome(True, content="done"),
        )

        assert seen == [900]

    def test_bash_offers_background_and_the_process_tools_have_a_kind(self) -> None:
        registry = builtin_registry()

        bash = registry.get("bash")
        assert bash is not None and bash.parameters["properties"]["background"]["type"] == "boolean"
        kinds = {name: registry.get(name).kind for name in ("process_output", "process_stop")}  # type: ignore[union-attr]
        assert kinds == {"process_output": "read", "process_stop": "write"}

    def test_the_timeout_description_names_the_ceiling(self) -> None:
        tool = builtin_registry().get("bash")

        assert tool is not None
        assert "remaining time" in tool.parameters["properties"]["timeout"]["description"]


class TestCompactDescriptions:
    """`describe_tools` leaves `full` byte-identical and shortens every built-in under `compact`."""

    @pytest.fixture(autouse=True)
    def _fetch_allowlisted(self) -> Iterator[None]:
        with use_home(
            dataclasses.replace(current_home(), fetch_allowed_domains=("api.example.test",))
        ):
            yield

    @staticmethod
    def _described(mode: str, **context: object) -> dict[str, str]:
        registry = builtin_registry()
        builtin_tools.describe_tools(registry, ToolContext(**context), mode)  # type: ignore[arg-type]
        return {spec.name: spec.description for spec in registry.specs()}

    @staticmethod
    def _today(**context: object) -> dict[str, str]:
        registry = builtin_registry()
        builtin_tools.describe_consult_for(registry, ToolContext(**context))  # type: ignore[arg-type]
        builtin_tools.state_bash_rules(registry, ToolContext(**context))  # type: ignore[arg-type]
        return {spec.name: spec.description for spec in registry.specs()}

    def test_full_is_what_a_turn_stated_before_profiles(self) -> None:
        assert self._described("full", allow_commands=("tox",)) == self._today(
            allow_commands=("tox",)
        )

    def test_every_built_in_is_at_most_two_sentences_and_shorter(self) -> None:
        full = self._described("full")
        compact = self._described("compact")

        assert compact.keys() == full.keys() and "fetch" in compact
        for name, text in compact.items():
            assert 1 <= sentence_count(text) <= 2, name
            assert len(text) < len(full[name]), name

    def test_fetch_says_a_long_page_is_read_back_with_read(self) -> None:
        text = self._described("compact")["fetch"]

        assert "read" in text and "kept whole" in text

    def test_bash_keeps_the_rules_of_this_turn(self) -> None:
        unjailed = self._described("compact", allow_commands=("tox",))["bash"]
        jailed = self._described("compact", sandbox="auto")["bash"]

        assert "tox" in unjailed and "git" in unjailed and "approval" in unjailed
        assert "any program" in jailed and "approval" in jailed

    @pytest.mark.parametrize(
        ("context", "words"),
        [
            ({"consult_park": True, "approval_mode": "park"}, ("ends your turn", "3 left")),
            ({"consult_park": True, "approval_mode": "wait"}, ("waits", "3 left")),
            ({"consult_park": True, "consult_mode": "decide"}, ("applied", "3 left")),
            ({"consult_park": False}, ("no answer", "3 left")),
        ],
    )
    def test_consult_keeps_its_effect_and_the_count(
        self, context: dict[str, object], words: tuple[str, ...]
    ) -> None:
        text = self._described("compact", max_consultations=3, **context)["consult"]

        assert all(word in text for word in words), text

    def test_a_bash_the_caller_made_is_left_alone(self) -> None:
        registry = builtin_registry()
        registry.register(dataclasses.replace(registry.get("bash"), description="mine"))  # type: ignore[type-var]

        builtin_tools.describe_tools(registry, ToolContext(), "compact")

        tool = registry.get("bash")
        assert tool is not None and tool.description == "mine"


class TestPodFetch:
    """A pod's `fetchDomains` offers `fetch` to its members, reaching those hosts only."""

    @staticmethod
    def _pod(name: str, **meta: object) -> None:
        path = current_home().meta_path(_pod.member_id(name, "lead"))
        path.parent.mkdir(parents=True, exist_ok=True)
        _store.write_json(path, {"kind": "project", "scope": "project", **meta})

    def test_an_empty_machine_list_and_a_pod_list_offer_fetch_to_that_pod(self) -> None:
        self._pod("docs", fetchDomains="docs.python.org")
        self._pod("bare")
        assert current_home().fetch_allowed_domains == ()
        assert "fetch" in builtin_registry("docs").names()
        assert "fetch" not in builtin_registry("bare").names()
        assert "fetch" not in builtin_registry().names()

    def test_the_pods_fetch_reaches_its_hosts_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._pod("docs", fetchDomains="docs.python.org,*.wikipedia.org")
        opened: list[str] = []

        class _Response:
            status = 200
            headers: ClassVar[dict[str, str]] = {"Content-Type": "text/plain"}

            def __enter__(self) -> _Response:
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read1(self, n: int) -> bytes:
                return b""

        class _Opener:
            def open(self, request: object, timeout: float = 0) -> _Response:
                opened.append(request.full_url)  # type: ignore[attr-defined]
                return _Response()

        monkeypatch.setattr(_fetch, "build_opener", lambda *_a, **_k: _Opener())
        registry = builtin_registry("docs")
        context = ToolContext(agent_id="t", roots=(Path("/tmp"),), role="reviewer", project="docs")

        def _fetch_of(url: str) -> object:
            call = ToolCall(id="c", name="fetch", arguments=json.dumps({"url": url}))
            return dispatch_tool(call, context, registry)

        assert _fetch_of("http://docs.python.org/3/").ok  # type: ignore[attr-defined]
        assert _fetch_of("http://es.wikipedia.org/wiki/Docket").ok  # type: ignore[attr-defined]
        refused = _fetch_of("http://example.org/")
        assert not refused.ok  # type: ignore[attr-defined]
        assert opened == ["http://docs.python.org/3/", "http://es.wikipedia.org/wiki/Docket"]

    def test_the_machine_list_and_the_pod_list_add_up(self) -> None:
        self._pod("docs", fetchDomains="docs.python.org")
        with use_home(
            dataclasses.replace(current_home(), fetch_allowed_domains=("api.example.test",))
        ):
            assert "fetch" in builtin_registry("").names()
            assert "fetch" in builtin_registry("docs").names()

    def test_a_pod_that_denies_fetch_holds_none_whatever_it_declares(self) -> None:
        self._pod("docs", fetchDomains="docs.python.org", deniedTools="fetch")
        narrowed = registry_for_role(builtin_registry("docs"), "implementer", project="docs")
        assert "fetch" not in narrowed.names()


class TestFetchRefusesACredentialInItsUrl:
    """A `fetch` URL that carries a credential is refused before `fetch_url` runs, at any host."""

    KEY = "sk-ant-" + "FAKE" * 6
    STORED = "zz/Opaque+Stored/Value/0123456789"

    @staticmethod
    def _fetch(url: str, allowed: tuple[str, ...] = ("example.org",)) -> tuple[object, list[str]]:
        seen: list[str] = []

        def _stub(called: str, _allowed: tuple[str, ...], _timeout: object) -> ToolOutcome:
            seen.append(called)
            return ToolOutcome(True, content="page")

        registry = ToolRegistry()
        registry.register(builtin_tools._fetch_tool(_stub, allowed))
        context = ToolContext(agent_id="t", roots=(Path("/tmp"),), role="reviewer", project="docs")
        call = ToolCall(id="c", name="fetch", arguments=json.dumps({"url": url}))
        return dispatch_tool(call, context, registry), seen

    def _assert_refused_without_the_value(
        self,
        url: str,
        leaked: tuple[str, ...],
        *,
        rule: str,
        allowed: tuple[str, ...] = ("example.org",),
    ) -> None:
        result, seen = self._fetch(url, allowed)
        assert seen == []
        assert not result.ok  # type: ignore[attr-defined]
        assert rule in result.error  # type: ignore[attr-defined]
        audit = json.dumps(_audit.read_audit())
        (entry,) = [e for e in _audit.read_audit() if e["action"] == "tool.refused"]
        assert "kind=fetch_secret_in_url" in str(entry["detail"])
        for value in leaked:
            assert value not in repr(result) and value not in audit

    @pytest.mark.parametrize(
        "template",
        [
            "https://example.org/?q={k}",
            "https://example.org/search?lang=en&api_key={k}",
            "https://example.org/v1/{k}/items",
            "https://example.org/page#{k}",
        ],
        ids=["query", "named-query-param", "path", "fragment"],
    )
    def test_a_provider_key_shape_anywhere_in_the_url_is_refused(self, template: str) -> None:
        self._assert_refused_without_the_value(
            template.format(k=self.KEY), (self.KEY, "FAKEFAKE"), rule="credential shape"
        )

    def test_a_percent_encoded_key_is_refused(self) -> None:
        encoded = "".join(f"%{byte:02X}" for byte in f"api_key={self.KEY}".encode())
        assert self.KEY not in encoded
        self._assert_refused_without_the_value(
            f"https://example.org/?q={encoded}", (self.KEY, "FAKEFAKE"), rule="credential shape"
        )

    @pytest.mark.parametrize("userinfo", ["u:pw0rd@", "u@"], ids=["user-and-password", "user-only"])
    def test_userinfo_is_refused(self, userinfo: str) -> None:
        self._assert_refused_without_the_value(
            f"https://{userinfo}example.org/", ("pw0rd", "u:pw"), rule="userinfo"
        )

    @pytest.mark.parametrize("encode", [False, True], ids=["raw", "percent-encoded"])
    def test_a_stored_secret_value_is_refused(self, encode: bool) -> None:
        _secrets.store_secret("PLAIN_NAME", self.STORED)
        text = urllib.parse.quote(self.STORED, safe="") if encode else self.STORED
        self._assert_refused_without_the_value(
            f"https://example.org/?q={text}", (self.STORED, "Opaque"), rule="credential shape"
        )

    def test_the_rule_holds_at_a_host_off_the_allowlist(self) -> None:
        result, seen = self._fetch(f"https://elsewhere.example/?q={self.KEY}")
        assert seen == [] and not result.ok  # type: ignore[attr-defined]
        (entry,) = [e for e in _audit.read_audit() if e["action"] == "tool.refused"]
        assert "kind=fetch_secret_in_url host='elsewhere.example'" in str(entry["detail"])

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.org/?q=ana%40example.org",
            "https://example.org/?q=ana@example.org",
            "https://example.org/docs/api-keys-and-tokens?page=2",
        ],
        ids=["encoded-address", "raw-address", "benign-words"],
    )
    def test_an_address_or_ordinary_words_are_not_a_credential(self, url: str) -> None:
        result, seen = self._fetch(url)
        assert seen == [url] and result.ok  # type: ignore[attr-defined]

    def test_a_key_encoded_twice_is_the_known_limit_and_reaches_the_fetch(self) -> None:
        url = "https://example.org/?q=%2573k-ant-" + "FAKE" * 6
        result, seen = self._fetch(url)
        assert seen == [url] and result.ok  # type: ignore[attr-defined]
