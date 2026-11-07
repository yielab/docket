"""The pins beside the server declarations (`teams/mcp_servers.py`): written through the JSON store,
global or pod-scoped, kept across a pod update and dropped with the server."""

from __future__ import annotations

import json

import pytest

from docket.kernel import mcp as _mcp
from docket.kernel.errors import InvalidInput
from docket.kernel.home import current_home
from docket.teams import mcp_servers as _mcp_servers

SUBJECT = "docket.teams.mcp_servers"


def _pin(name: str, description: str = "d") -> _mcp.McpToolPin:
    return _mcp.McpToolPin(hash=_mcp.tool_pin(name, description, {}), description=description)


def _server(name: str = "web") -> _mcp.McpServerConfig:
    return _mcp.McpServerConfig(name=name, command="stub", kind="read")


class TestPinsBesideTheDeclaration:
    def test_no_pins_until_one_is_written(self) -> None:
        _mcp_servers.add_mcp_server(_server())

        assert _mcp_servers.load_pins() == {}

    def test_a_pin_is_written_into_the_servers_file_and_read_back_as_hashes(self) -> None:
        _mcp_servers.add_mcp_server(_server())

        _mcp_servers.pin_server("web", {"lookup": _pin("lookup")})

        assert _mcp_servers.load_pins() == {"web": {"lookup": _pin("lookup").hash}}
        raw = json.loads(current_home().mcp_servers_file.read_text())
        assert raw["pins"]["web"]["lookup"]["description"] == "d"
        assert [s["name"] for s in raw["servers"]] == ["web"]

    def test_an_empty_pin_set_still_marks_the_server_pinned(self) -> None:
        _mcp_servers.add_mcp_server(_server())

        _mcp_servers.pin_server("web", {})

        assert _mcp_servers.load_pins() == {"web": {}}

    def test_pinning_a_server_nobody_declared_is_refused(self) -> None:
        with pytest.raises(InvalidInput, match="ghost"):
            _mcp_servers.pin_server("ghost", {})

    def test_adding_another_server_keeps_the_pins(self) -> None:
        _mcp_servers.add_mcp_server(_server("web"))
        _mcp_servers.pin_server("web", {"lookup": _pin("lookup")})

        _mcp_servers.add_mcp_server(_server("crm"))

        assert "web" in _mcp_servers.load_pins()

    def test_removing_a_server_drops_its_pins_and_pending_and_keeps_the_others(self) -> None:
        _mcp_servers.add_mcp_server(_server("web"))
        _mcp_servers.add_mcp_server(_server("crm"))
        for name in ("web", "crm"):
            _mcp_servers.pin_server(name, {"t": _pin("t")})
        _mcp_servers.record_pending("web", {"t": _pin("t", "changed")})

        assert _mcp_servers.remove_mcp_server("web") is True

        assert list(_mcp_servers.load_pins()) == ["crm"]
        assert "web" not in json.loads(current_home().mcp_servers_file.read_text())["pending"]

    def test_a_pod_scoped_server_keeps_its_pins_in_the_pods_own_file(self) -> None:
        _mcp_servers.write_pod_mcp_servers("p1", [_server("own")])

        _mcp_servers.pin_server("own", {"t": _pin("t")}, project="p1")

        assert _mcp_servers.load_pins("p1") == {"own": {"t": _pin("t").hash}}
        assert _mcp_servers.load_pins() == {}
        assert "own" in json.loads(_mcp_servers.pod_mcp_servers_file("p1").read_text())["pins"]

    def test_rewriting_a_pod_file_keeps_the_pins_of_servers_that_stay_only(self) -> None:
        _mcp_servers.write_pod_mcp_servers("p1", [_server("keep"), _server("drop")])
        for name in ("keep", "drop"):
            _mcp_servers.pin_server(name, {"t": _pin("t")}, project="p1")

        _mcp_servers.write_pod_mcp_servers("p1", [_server("keep")])

        assert list(_mcp_servers.load_pins("p1")) == ["keep"]


class TestAcceptingWhatATurnObserved:
    def _held(self) -> None:
        _mcp_servers.add_mcp_server(_server())
        _mcp_servers.pin_server("web", {"lookup": _pin("lookup"), "gone": _pin("gone")})
        _mcp_servers.record_pending(
            "web", {"lookup": _pin("lookup", "now also mails you"), "extra": _pin("extra")}
        )

    def test_the_changes_name_what_was_added_removed_and_changed_with_both_descriptions(
        self,
    ) -> None:
        self._held()

        changes = {c.tool: c for c in _mcp_servers.accept_pending("web")}

        assert changes["lookup"].kind == "changed"
        assert (changes["lookup"].old, changes["lookup"].new) == ("d", "now also mails you")
        assert changes["extra"].kind == "added" and changes["gone"].kind == "removed"

    def test_accepting_replaces_the_pins_with_the_pending_listing_and_clears_it(self) -> None:
        self._held()

        _mcp_servers.accept_pending("web")

        assert set(_mcp_servers.load_pins()["web"]) == {"lookup", "extra"}
        assert (
            _mcp_servers.load_pins()["web"]["lookup"] == _pin("lookup", "now also mails you").hash
        )
        with pytest.raises(InvalidInput, match="nothing pending"):
            _mcp_servers.accept_pending("web")

    def test_accepting_with_nothing_pending_is_refused_naming_the_server(self) -> None:
        _mcp_servers.add_mcp_server(_server())

        with pytest.raises(InvalidInput, match="web"):
            _mcp_servers.accept_pending("web")

    def test_an_unknown_server_is_refused(self) -> None:
        with pytest.raises(InvalidInput, match="ghost"):
            _mcp_servers.accept_pending("ghost")

    def test_a_pod_scoped_server_is_accepted_without_naming_its_pod(self) -> None:
        (current_home().pods_dir / "p1").mkdir(parents=True)
        _mcp_servers.write_pod_mcp_servers("p1", [_server("own")])
        _mcp_servers.pin_server("own", {"t": _pin("t")}, project="p1")
        _mcp_servers.record_pending("own", {"t": _pin("t", "changed")}, project="p1")

        _mcp_servers.accept_pending("own")

        assert _mcp_servers.load_pins("p1")["own"]["t"] == _pin("t", "changed").hash
