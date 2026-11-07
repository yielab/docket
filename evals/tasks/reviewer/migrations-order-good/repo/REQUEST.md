# Request

pending(applied, available) must return the unapplied names in migration-number order: the
integer before the first underscore ('7_backfill_plan' comes before '10_index'), whatever the
order of available.
