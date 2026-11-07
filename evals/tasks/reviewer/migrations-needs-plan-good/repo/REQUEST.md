# Request

needs_plan(rows): the ids of the account rows (dicts with 'id' and 'plan_id') that have no plan
yet, that is plan_id is None. plan_id 0 is the free plan, a real plan: not missing.
