from datetime import UTC, datetime

import dates


def test_to_storage_is_utc():
    assert dates.to_storage(datetime(2026, 11, 7, 9, 0, tzinfo=UTC)) == "2026-11-07T09:00:00Z"
