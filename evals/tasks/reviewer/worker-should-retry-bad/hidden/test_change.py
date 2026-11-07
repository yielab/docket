import worker


def test_only_transient_errors_are_retried():
    assert worker.should_retry(TimeoutError(), 2) is True
    assert worker.should_retry(FileNotFoundError("queue.db"), 1) is False
    assert worker.should_retry(PermissionError("queue.db"), 1) is False
