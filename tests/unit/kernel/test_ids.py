"""``kernel.ids`` -- the shape of each minted id, which callers and stored data match on."""

from __future__ import annotations

import re
import uuid

from docket.kernel.ids import new_id, new_short_id, new_uuid

SUBJECT = "docket.kernel.ids"

_UUID4 = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"


def test_new_id_is_the_prefix_and_a_uuid4() -> None:
    assert re.fullmatch(rf"apr-{_UUID4}", new_id("apr"))


def test_new_short_id_is_the_prefix_and_twelve_hex_chars() -> None:
    assert re.fullmatch(r"q-[0-9a-f]{12}", new_short_id("q"))
    assert re.fullmatch(r"docket-sbx-[0-9a-f]{12}", new_short_id("docket-sbx"))


def test_new_uuid_is_a_bare_uuid4() -> None:
    assert uuid.UUID(new_uuid()).version == 4


def test_ids_do_not_repeat() -> None:
    assert len({new_id("task") for _ in range(500)}) == 500
