"""``teams.apply.lock``: the lock a directory would write, its digest, and the drift it answers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from docket.kernel.home import current_home
from docket.teams.apply import lock as _lock

SUBJECT = "docket.teams.apply.lock"

_ROLE = "kind: role\nname: vetter\nmodel: cheap\nversion: 2\n"
_PROMPT = (
    "---\nkind: prompt\nname: reviewer\nversion: 1.2.0\nlayer: hop\nfor: reviewer\n---\nText\n"
)


def _directory(root: Path) -> Path:
    base = root / "repo" / ".docket"
    (base / "roles").mkdir(parents=True)
    (base / "roles" / "vetter.yaml").write_text(_ROLE)
    (base / "roles" / "vetter.md").write_text("Vet.\n")
    (base / "prompts" / "hop").mkdir(parents=True)
    (base / "prompts" / "hop" / "reviewer.md").write_text(_PROMPT)
    (base / "policies").mkdir()
    (base / "policies" / "p.yaml").write_text("kind: policy\nname: p\n")
    (base / "plugins").mkdir()
    (base / "plugins" / "x.py").write_text("x = 1\n")
    (base / "pipelines").mkdir()
    (base / "pipelines" / "fast.yaml").write_text("name: fast\n")
    (base / "mcp-servers").mkdir()
    (base / "mcp-servers" / "s.yaml").write_text("kind: mcp-server\nname: s\ncommand: c\n")
    (base / "skills" / "k").mkdir(parents=True)
    (base / "skills" / "k" / "SKILL.md").write_text("---\nname: k\n---\n")
    (base / "pod.yaml").write_text("kind: pod\nname: t\n")
    return base


def _by(items: tuple[_lock.LockItem, ...]) -> dict[str, _lock.LockItem]:
    return {f"{i.kind}:{i.name}": i for i in items}


def test_every_file_the_directory_brings_is_an_item_with_its_source_path_and_hash(
    tmp_path: Path,
) -> None:
    base = _directory(tmp_path)

    items = _by(_lock.source_items(base))

    assert set(items) == {
        "role:vetter",
        "prompt:reviewer",
        "policy:p",
        "plugin:x",
        "pipeline:fast",
        "mcp-server:s",
        "skill:k",
        "pod:pod.yaml",
    }
    role = items["role:vetter"]
    assert (role.version, role.scope, role.applied) == ("2", "repository", "roles/vetter.yaml")
    assert role.path == str((base / "roles" / "vetter.yaml").resolve())
    assert role.sha256 == hashlib.sha256((_ROLE + "Vet.\n").encode()).hexdigest()
    prompt = items["prompt:reviewer"]
    assert (prompt.version, prompt.applied) == ("1.2.0", "prompts/hop/reviewer.md")
    assert prompt.sha256 == hashlib.sha256(_PROMPT.encode()).hexdigest()
    assert items["mcp-server:s"].applied == ""
    assert items["pod:pod.yaml"].applied == ""
    assert items["skill:k"].applied == "skills/k"


def test_items_are_sorted_by_kind_then_name(tmp_path: Path) -> None:
    items = _lock.source_items(_directory(tmp_path))

    keys = [(i.kind, i.name) for i in items]
    assert keys == sorted(keys)


def test_the_digest_is_the_sha256_of_the_rendered_text_the_store_writes(tmp_path: Path) -> None:
    items = _lock.source_items(_directory(tmp_path))

    assert _lock.digest_of(items) == hashlib.sha256(_lock.render(items).encode()).hexdigest()
    assert _lock.write_lock("acme", items) == _lock.digest_of(items)
    on_disk = _lock.lock_path("acme").read_bytes()
    assert on_disk == _lock.render(items).encode()
    assert json.loads(on_disk)["items"][0]["kind"] == items[0].kind
    assert _lock.read_lock("acme") == items


def test_editing_a_source_file_moves_the_digest(tmp_path: Path) -> None:
    base = _directory(tmp_path)
    before = _lock.source_digest(base)

    (base / "plugins" / "x.py").write_text("x = 2\n")

    assert _lock.source_digest(base) != before


def test_the_scope_is_where_the_directory_came_from(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    (plain / "plugins").mkdir(parents=True)
    (plain / "plugins" / "x.py").write_text("x\n")

    assert _lock.source_items(plain)[0].scope == "operator"
    assert _lock.source_items(_directory(tmp_path))[0].scope == "repository"
    shipped = next(p for p in _lock._templates.RECIPES_DIR.iterdir() if p.is_dir())
    assert {i.scope for i in _lock.source_items(shipped)} == {"shipped"}


def test_overlay_drift_is_an_applied_file_that_no_longer_hashes_to_its_item(
    tmp_path: Path,
) -> None:
    base = _directory(tmp_path)
    overlay = current_home().pod_config_dir("acme")
    (overlay / "roles").mkdir(parents=True)
    for rel in ("roles/vetter.yaml", "roles/vetter.md"):
        (overlay / rel).write_bytes((base / rel).read_bytes())
    items = tuple(i for i in _lock.source_items(base) if i.kind == "role")
    _lock.write_lock("acme", items)
    assert _lock.overlay_drifted("acme") is False

    (overlay / "roles" / "vetter.md").write_text("changed\n")
    assert _lock.overlay_drifted("acme") is True

    (overlay / "roles" / "vetter.md").unlink()
    assert _lock.overlay_drifted("acme") is True


def test_a_pod_with_no_lock_has_no_overlay_drift() -> None:
    assert _lock.read_lock("acme") is None
    assert _lock.overlay_drifted("acme") is False


def test_drift_compares_the_source_lock_with_what_was_recorded(tmp_path: Path) -> None:
    base = tmp_path / "team"
    base.mkdir()
    (base / "pod.yaml").write_text("kind: pod\nname: t\n")  # an item with no overlay copy
    recorded = _lock.write_lock("acme", _lock.source_items(base))

    assert _lock.drift("acme", str(base), recorded) == "no"
    (base / "pod.yaml").write_text("kind: pod\nname: t2\n")
    assert _lock.drift("acme", str(base), recorded) == "yes"
    assert _lock.drift("acme", "", recorded) == ""


def test_a_missing_source_directory_is_judged_by_its_overlay_alone(tmp_path: Path) -> None:
    gone = tmp_path / "gone"
    assert _lock.drift("acme", str(gone), "0" * 64) == ""  # no lock either: nothing to compare

    _lock.write_lock("acme", ())
    assert _lock.drift("acme", str(gone), "0" * 64) == "no"


def test_a_roles_json_beside_the_overlay_is_ignored_and_is_not_drift() -> None:
    _lock.write_lock("acme", ())
    stray = current_home().pod_config_dir("acme") / "roles.json"
    stray.write_text("{}")

    assert _lock.overlay_drifted("acme") is False
    assert not hasattr(_lock, "needs_update")
    assert stray.read_text() == "{}"
