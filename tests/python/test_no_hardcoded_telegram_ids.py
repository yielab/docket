"""Guard: no hardcoded Telegram chat IDs in tracked files (they stay dynamic).

Telegram group/chat IDs are runtime data — they live only in
``~/.openclaw/openclaw.json`` and reach docket through the ACL. A real ID once
slipped into a test fixture and was published to the public repo; this scan makes
that impossible to repeat silently.

Rules:
- ``src/`` must contain **no** Telegram-ID-shaped literal at all (the code reads
  IDs dynamically — nothing is hardcoded).
- Any other tracked file may use only a small allowlist of **obviously-synthetic**
  placeholders (:data:`SANCTIONED_FAKE_IDS`). A new placeholder must be added here
  consciously, so a *real* ID — which will never match the allowlist — fails CI.

Scans **tracked** files only (``git ls-files``), so gitignored analysis notes that
legitimately reference real IDs are out of scope. Sibling of
``test_ch3_no_ui_in_core_edges.py`` / ``test_ch4_no_subprocess_in_core.py``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

import docket

_REPO_ROOT = Path(docket.__file__).resolve().parents[2]

#: Obviously-synthetic Telegram IDs tests/docs/fixtures are allowed to use.
#: Add a new fake here *consciously* — a real ID will never match and thus fails.
SANCTIONED_FAKE_IDS = frozenset(
    {
        "-1001234567890",  # the canonical Telegram example id (preferred)
        "-123456789",  # multi-group wire-picker tests
        "-999888777",  # multi-group wire-picker tests
    }
)

#: Telegram chat/group IDs are standalone negative integers of 9+ digits. The
#: look-behind excludes ``word-1234567890`` (e.g. ``task-1720000000000`` ids).
_TG_ID = re.compile(r"(?<![\w-])-\d{9,}(?!\d)")


def _telegram_ids_in(path: Path) -> list[str]:
    try:
        return _TG_ID.findall(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return []


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "ls-files"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return [_REPO_ROOT / line for line in out.stdout.splitlines() if line]


def test_no_unsanctioned_telegram_ids_in_tracked_files() -> None:
    if not (_REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    self_path = Path(__file__).resolve()
    offenders: dict[str, list[str]] = {}
    for f in _tracked_files():
        if f.resolve() == self_path:
            continue  # this file defines the allowlist
        bad = sorted({i for i in _telegram_ids_in(f) if i not in SANCTIONED_FAKE_IDS})
        if bad:
            offenders[str(f.relative_to(_REPO_ROOT))] = bad
    assert not offenders, (
        "Hardcoded Telegram-ID-shaped literals found — make it dynamic or use a "
        f"sanctioned fake ({sorted(SANCTIONED_FAKE_IDS)}): {offenders}"
    )


def test_source_never_hardcodes_a_telegram_id() -> None:
    src = _REPO_ROOT / "src"
    offenders = {
        str(p.relative_to(_REPO_ROOT)): sorted(set(ids))
        for p in src.rglob("*.py")
        if (ids := _telegram_ids_in(p))
    }
    assert not offenders, f"src/ must never hardcode a Telegram ID (keep it dynamic): {offenders}"
