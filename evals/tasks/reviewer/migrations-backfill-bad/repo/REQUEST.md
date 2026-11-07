# Request

backfill_plan(rows, default_plan_id): return NEW account rows where a missing plan_id (None) is
replaced by default_plan_id and all other values are kept. The rows passed in are not modified.
