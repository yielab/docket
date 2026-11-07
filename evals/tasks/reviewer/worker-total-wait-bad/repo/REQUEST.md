# Request

total_wait(retries): the seconds a task waits in all over its first retries retries, that is
the sum of backoff_delay(1) ... backoff_delay(retries). 0 retries wait 0 seconds.
