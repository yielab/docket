# Request

jittered_delay(attempt, unit): backoff_delay(attempt) scaled by 0.8 + 0.4 * unit, where unit is
a number in [0, 1) the caller draws. The result must never exceed MAX_DELAY_S.
