"""The field checks a provider, an exporter and a channel document share."""

from __future__ import annotations

import re

from docket.kernel.errors import InvalidInput

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_CREDENTIAL_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_CREDENTIAL_VALUE_RE = re.compile(r"^[A-Za-z0-9/_\-+.]{20,}$")
_RESERVED_HEADERS = frozenset({"authorization", "content-type", "accept"})


def check_name(value: str, what: str) -> str:
    """*value* unchanged, or ``InvalidInput`` saying it is not a valid *what* name."""
    if not NAME_RE.match(value):
        raise InvalidInput(f"'{value}' is not a valid {what} name (^[a-z0-9][a-z0-9-]*$)")
    return value


def check_http_url(value: str) -> str:
    if not (value.startswith("http://") or value.startswith("https://")):
        raise InvalidInput(f"'{value}' must be an http:// or https:// URL")
    return value


def check_credential_name(name: str, field: str) -> str:
    """*name* unchanged when it names a stored secret; a secret's value pasted into *field* gets
    its own refusal, because it must never reach a document on disk."""
    if _CREDENTIAL_NAME_RE.match(name):
        return name
    if _CREDENTIAL_VALUE_RE.match(name):
        raise InvalidInput(
            f"'{name}' looks like a credential VALUE, not a name -- "
            f"{field} names a stored secret, it never carries one"
        )
    raise InvalidInput(f"'{name}' is not a valid credential name (^[A-Z][A-Z0-9_]*$)")


def reject_reserved_headers(value: dict[str, str]) -> dict[str, str]:
    """*value* unchanged, or ``InvalidInput`` naming the first header docket sends itself."""
    for key in value:
        if key.strip().lower() in _RESERVED_HEADERS:
            raise InvalidInput(
                f"'{key}' is a reserved header name "
                "(authorization, content-type, accept are sent by docket itself)"
            )
    return value
