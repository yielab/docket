# Service Client Specification

**Version**: 1.0.0
**Status**: The HTTP executor and its perimeter (`platform/service_http.py::call_operation`) are
specified here and tested; no document, tool or CLI calls it yet (the document and its
registration are P56-3 and later), so a pod cannot reach a service through it today.
**Last Updated**: 2026-10-30

## Purpose

ADR 0036 decisions 13 and 14 let a pod reach an HTTP service nobody wrote an MCP server for: a
service is a document and each operation of it is a tool. This specification defines the half that
touches the network: the call one operation makes, and the perimeter that call stays inside. The
caller is docket's own process, not the jail (as `fetch` is), so the perimeter is the service's
host alone.

## Scope

This specification covers:

- `call_operation`: building the URL from a path template, sending JSON, and shaping the outcome
- The perimeter: which hosts and addresses a call may reach, redirects, header hygiene, the bounds on
  time and size, and what never appears in an outcome

It does NOT cover the `kind: service` document, its registration, the tool each operation becomes,
approval, audit or the quota (the rest of this specification), retries, pagination, multipart or
binary bodies, or OAuth.

## Requirements

### The call

1. `call_operation(request) -> ToolOutcome` (`docket.platform.service_http`) **MUST** take a `ServiceRequest`
   carrying the method, the service's `base_url`, a path template, the values for its `{name}`
   parameters, a query mapping, the headers, an optional JSON body and the extra `hosts` the document
   lists. The caller resolves a secret before building the request; `platform` imports nothing from
   `governance`.
2. The method **MUST** be one of `GET`, `POST`, `PUT`, `PATCH`, `DELETE`; any other is refused.
3. The URL **MUST** be the `base_url` (without a trailing slash) followed by the path template with
   each `{name}` replaced by its value percent-encoded with no safe characters, so a value holding
   `/`, `?`, `#` or `..` stays one path segment and is never concatenated raw. A value that is `.` or
   `..` on its own, a `{name}` with no value, and a `{name}` left in the result **MUST** be refused.
   The query mapping is appended encoded, a boolean as `true` or `false`.
4. A body, when given, **MUST** be sent as compact JSON with `Content-Type: application/json`.
5. A 2xx response whose body parses as JSON **MUST** return `ok` with that JSON re-serialised
   compactly; any other 2xx body **MUST** return `ok` with the text, decoded as UTF-8 with
   replacement.
6. A non-2xx response **MUST** return a failed outcome whose `error` names the status code, the method
   and the host and path (never the query), and the head of the body (at most 500 characters).
7. A connection error or a timeout **MUST** return a failed outcome naming the host; nothing raises.

### The perimeter

8. The host of the URL **MUST** be the host of `base_url` or one of `hosts` (compared in lowercase);
   `base_url` **MUST** be `http` or `https` with a host and no embedded credentials. Otherwise the call
   is refused (`refusal="service_not_allowed"`) before any socket is opened.
9. A redirect **MUST NOT** be followed to a host outside that set, or to a scheme that downgrades `https`
   to `http`; the refusal is reported as in Requirement 8. A redirect inside the set is followed.
10. Every address the host resolves to **MUST** be checked before connecting; the call **MUST** connect
    to the address it checked. A private, loopback, link-local, multicast, reserved or unspecified
    address **MUST** be refused (`refusal="service_not_allowed"`) unless the host is listed
    in `hosts` explicitly: being the `base_url` host is not enough. System proxy settings **MUST NOT**
    apply, since a proxy would move the connection past the check.
11. A header name **MUST** be an HTTP token and a header value **MUST NOT** contain CR, LF or NUL; a
    header named `Host`, `Content-Length` or `Transfer-Encoding` **MUST** be refused. A violation is
    refused (`refusal="service_bad_request"`) before any socket is opened.
12. The call **MUST** be bounded in time by `Home.fetch_timeout_s` (the whole call, headers and body)
    and in size by `Home.fetch_max_response_bytes`: a body over the cap is cut at it and the content
    ends with `[truncated: response exceeded <N> bytes]`, so a cut body is returned as text, never as
    JSON.
13. The value of any header named `Authorization`, `Proxy-Authorization`, `Cookie`, or containing
    `key`, `token`, `secret` or `auth`, each word of it, and every value in the request's `secrets`
    **MUST** be replaced by `[REDACTED]` wherever it appears in the outcome's `content` or `error`, so
    a server that echoes the credential back does not hand it to the model.

## Interface Contracts

```python
@dataclass(frozen=True)
class ServiceRequest:
    method: str
    base_url: str
    path: str = ""
    path_params: Mapping[str, str] = {}
    query: Mapping[str, object] = {}
    headers: Mapping[str, str] = {}
    body: object | None = None
    hosts: tuple[str, ...] = ()
    secrets: tuple[str, ...] = ()

def call_operation(request: ServiceRequest) -> ToolOutcome: ...
```

Refusal kinds: `service_not_allowed` (the perimeter: host, redirect, address) and `service_bad_request`
(the request: method, path, headers).

## Examples

A request `GET http://127.0.0.1:8123` with `path="/items/{id}"` and `path_params={"id": "../x"}` calls
`/items/..%2Fx`. The same request with `hosts=()` is refused with `service_not_allowed` before
a socket opens; with `hosts=("127.0.0.1",)` it is sent.

## Validation

- `tests/integration/platform/test_service_http.py` drives `call_operation` against a loopback
  `http.server`.
- `tests/unit/platform/test_service_http.py` covers the pure helpers: URL building, header checks,
  address classification and redaction.
