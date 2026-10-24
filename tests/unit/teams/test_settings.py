"""POST /tasks/<project> — enqueue a task over HTTP.

See specs/data/serve-read-api.spec.md ("POST /tasks/<project>") for the
endpoint contract this suite pins. Test classes: TestAuth (Bearer-gated
like ``/dispatch/`` and ``/runs``), TestBadRequests (malformed/invalid
bodies are 400 before ``enqueue_task_once`` runs), TestMissingPod (no pod is
404, not 500), TestPolicyGates (``pre_input`` gate behaves as the CLI
path does, since this route calls the same ``enqueue_task_once``),
TestSuccess (happy path), and TestExecuteUnitDirectly (``_execute_unit``
and two extracted phases, called directly with a hand-built
``_UnitContext``/``PlannedUnit``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support import pods as _support_pods
from tests.support.pods import write_meta as _write_meta

from docket.tasks.domain import task as _task
from docket.teams import settings as _settings

pod_home = _support_pods.pod_home_bare

SUBJECT = "docket.teams.settings"


# ── fixtures ──────────────────────────────────────────────────────────────────


class TestPodSettingReaders:
    """Each Lead-meta setting reader routes through ``teams.pod_settings.PodSettings`` --
    a valid override reads through, and an invalid stored value refuses
    dispatch instead of silently substituting the field's default."""

    def test_pod_budget_reads_through(self, pod_home: Path) -> None:
        _write_meta("myapp-lead", {"budgetUsd": "12.5"})
        assert _settings.pod_budget("myapp") == 12.5

    def test_pod_budget_invalid_value_refuses(self, pod_home: Path) -> None:
        _write_meta("myapp-lead", {"budgetUsd": "not-a-number"})
        with pytest.raises(_task.DispatchError, match="budgetUsd"):
            _settings.pod_budget("myapp")

    def test_pod_verify_timeout_invalid_value_refuses(self, pod_home: Path) -> None:
        _write_meta("myapp-lead", {"verifyTimeoutS": "0"})
        with pytest.raises(_task.DispatchError, match="verifyTimeoutS"):
            _settings.pod_verify_timeout("myapp")

    def test_pod_approval_mode_defaults_to_wait(self, pod_home: Path) -> None:
        _write_meta("myapp-lead")
        assert _settings.pod_approval_mode("myapp") == "wait"

    def test_pod_approval_mode_reads_through(self, pod_home: Path) -> None:
        _write_meta("myapp-lead", {"approvalMode": "refuse"})
        assert _settings.pod_approval_mode("myapp") == "refuse"

    def test_pod_approval_mode_invalid_value_refuses(self, pod_home: Path) -> None:
        _write_meta("myapp-lead", {"approvalMode": "sometimes"})
        with pytest.raises(_task.DispatchError, match="approvalMode"):
            _settings.pod_approval_mode("myapp")

    def test_pod_approval_mode_unset_resolves_through_caller_default(self, pod_home: Path) -> None:
        """ADR 0016 SS2: an unset pod ``approvalMode`` defers to the caller, not a fixed
        "wait" -- `serve --dispatch`'s sweep passes "park", a foreground TTY dispatch "wait"."""
        _write_meta("myapp-lead")
        assert _settings.pod_approval_mode("myapp", caller_default="park") == "park"
        assert _settings.pod_approval_mode("myapp", caller_default="wait") == "wait"

    def test_pod_approval_mode_explicit_value_wins_over_caller_default(
        self, pod_home: Path
    ) -> None:
        _write_meta("myapp-lead", {"approvalMode": "refuse"})
        assert _settings.pod_approval_mode("myapp", caller_default="park") == "refuse"

    def test_pod_approval_mode_is_set_false_when_unset(self, pod_home: Path) -> None:
        _write_meta("myapp-lead")
        assert _settings.pod_approval_mode_is_set("myapp") is False

    def test_pod_approval_mode_is_set_true_when_set(self, pod_home: Path) -> None:
        _write_meta("myapp-lead", {"approvalMode": "park"})
        assert _settings.pod_approval_mode_is_set("myapp") is True
