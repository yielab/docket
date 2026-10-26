"""The webhook dialect's signature."""

from __future__ import annotations

import base64
import hmac

from docket.operator.adapters import webhook

SUBJECT = "docket.operator.adapters.webhook"


class TestSignature:
    def test_matches_the_standard_webhooks_test_vector(self) -> None:
        secret_value = "whsec_" + base64.b64encode(b"test-secret").decode()
        body = b'{"a":1}'
        expected_digest = hmac.new(b"test-secret", b"msg_1.1700000000." + body, "sha256").digest()
        expected = "v1," + base64.b64encode(expected_digest).decode()

        actual = webhook._sign(secret_value, "msg_1", "1700000000", body)
        assert actual == expected
