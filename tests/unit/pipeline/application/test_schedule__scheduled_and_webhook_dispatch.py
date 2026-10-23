"""Scheduled & webhook-triggered dispatch.

Acceptance criteria: a scheduled time fires a dispatch, a webhook POST
triggers a dispatch, unauthorized requests are rejected.

The last-run bookkeeping ``TestCheckSchedules`` exercises must be durable
state in the schedules file (``core.schedule.load_last_run``/
``record_last_run``), never an in-memory ``_serve._schedule_state`` dict --
an in-memory dict resets on restart and re-fires every schedule
immediately. The restart-survival test lives here; per-dispatch run-record
coverage lives in ``test_dispatch_run_records.py``.
"""

from __future__ import annotations

SUBJECT = "docket.pipeline.application.schedule"
