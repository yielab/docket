# Request

should_retry(error, attempt, max_attempts=5): True when the failed attempt number attempt is
below max_attempts and the error is transient: ConnectionResetError or TimeoutError. Any other
error (FileNotFoundError, ValueError, ...) is not retried.
