# Earlier work in this session (state at the pause)

Decision: run migration 0007 before the deploy, not after, because plan_id becomes NOT NULL.

I ran `alembic upgrade head`; the last line was:
IntegrityError: null value in column plan_id of relation accounts (14 rows)

Fix: edited migrations/0007_backfill_plan.py: the backfill now sets plan_id to 'free' before the constraint.

The test passes now. Still open: scripts/seed_demo.py inserts accounts without a plan_id.

Operator: thanks, pause here. The files that follow are the tool output of the run.
