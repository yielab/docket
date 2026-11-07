# Request

TokenChecker(clock=time.time).expired(issued_at): the same rule as is_expired but reading the
time from the injected clock (a zero-argument callable returning seconds), so that tests never
patch time. The clock is called at each check.
