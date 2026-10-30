# Service Client Specification

**Version**: 1.1.0
**Status**: Implemented in part: the document, its access rule, its registration and its scopes
(`kernel/service.py`, `teams/services.py`, `docket setup service`, `docket pod update|export`), and
the call with its perimeter (`platform/service_http.py::call_operation`). No operation is a tool yet
and nothing calls the executor: the tools are separate work.
**Last Updated**: 2026-10-30

## Purpose

A pod reaches an external HTTP service without anyone writing a program for it. A service is a
document: its address, how it authenticates, and the operations a pod may perform on it, each with
the access it needs. docket reads the document, keeps it, and (in later work) turns each operation
into a tool that passes `dispatch_tool` like any other. This specification defines the document,
the rule that decides what an operation may do, and the call one operation makes: the half that
touches the network, and the perimeter that call stays inside. The caller is docket's own process,
not the jail (as `fetch` is), so the perimeter is the service's host alone. It is the declared-service counterpart of the MCP
client (`mcp-client.spec.md`), which reaches a service through a program someone wrote.

## Scope

This specification covers:

- The `kind: service` document and its typed form (`ServiceConfig`, `Operation`)
- The access of an operation and the rule that bounds it by its HTTP method
- Where a service is kept (the operator's file, a pod's `services/` directory) and how it travels
  (`pod update`, `pod export`)
- The rule that a service and an MCP server never share a name
- `docket setup service add|list|remove`
- `call_operation`: building the URL from a path template, sending JSON, and shaping the outcome
- The perimeter: which hosts and addresses a call may reach, redirects, header hygiene, the bounds on
  time and size, and what never appears in an outcome

This specification does NOT cover:

- Resolving a secret (the caller does, before it builds the request)
- Retries, pagination, multipart or binary bodies
- Turning an operation into a tool, its quota or its approval (the tools)
- Importing operations from an OpenAPI document
- OAuth grants of any kind

## Requirements

### The document

1. A service **MUST** be a YAML or JSON document of `ServiceDocument` (`extra="forbid"`; an unknown
   key at any level is refused naming it): `kind` (`service`), `name`, `baseUrl`, an optional
   `auth`, `hosts`, `timeout`, `idempotencyHeader` and `operations`.
2. `name` **MUST** contain only letters, digits, `-` and `_`. `baseUrl` **MUST** be an `http` or
   `https` URL with a host and no user information, query or fragment. `hosts` is a list of extra
   host names the service may be called on (default none). `timeout` is a number of seconds, not
   negative, `0` meaning the default. `idempotencyHeader` is an optional header name.
3. `auth` is `{header, value}`: a header name and the header's value. A `value` **MAY** contain
   `${secret:<name>}` references (`<name>` is letters, digits, `-`, `_`, `.`); a reference not
   written that way is refused. A reference **MUST** be kept as written everywhere the document is
   loaded, stored, listed or exported; no function of this specification resolves one, and a
   listing shows the header and the secret names a value references, never the value.
4. An operation is `name`, `method` (`GET`, `POST`, `PUT`, `PATCH` or `DELETE`), `path`, `params`,
   `body`, `access` and `description`. Operation names are unique within a service and contain
   only letters, digits, `-` and `_`.
5. A `path` **MUST** begin with `/`. Each `{param}` placeholder in it **MUST** be a declared
   parameter with `in: path`, and each `in: path` parameter **MUST** appear in the path; either
   mismatch is refused naming the operation and the parameter. A path parameter is always
   required.
6. A parameter is `name` (unique within the operation), `in` (`path` or `query`), `type`
   (`string`, `integer`, `number` or `boolean`; default `string`) and `required` (default `false`).
7. `body` is absent, or a JSON Schema object (a mapping whose `type`, when given, is `object`).
   An operation with method `GET` **MUST NOT** declare a body.
8. A document that fails any rule above **MUST** be refused as a whole, naming the file and the
   first failing field, and nothing **MUST** be written.
9. A document **MUST** round-trip: the loaded `ServiceConfig` dumped by alias (access resolved,
   defaults left out) under `kind: service` loads to an equal `ServiceConfig`.

### Access

10. An operation's `access` is `read` or `send`. Omitted, it is `read` for `GET` and `send` for
    every other method. `GET` **MAY** declare `send`.
11. `POST`, `PUT`, `PATCH` and `DELETE` **MUST** be `send`: a document declaring one of them
    `read` **MUST** be refused, naming the operation. No other `access` value exists.
12. The access an operation resolves to **MUST** be part of its typed form, so the tool built from
    it (later work) never re-derives it from the method.

### Scopes and names

13. The operator's services **MUST** be docket-owned state in `services.json` under the config
    directory of `DOCKET_HOME`, written only through `platform/store.py`. A pod's own services
    **MUST** be the files `services/<name>.yaml` (or `.yml`) in its overlay, copied byte for byte
    by `docket pod update` and written back by `docket pod export`.
14. A service read for a pod **MUST** resolve its own before the operator's, by name. A `pod
    update` whose directory declares a name equal to an operator's service, or declares one name
    twice, **MUST** be refused naming it, and nothing **MUST** be written.
15. A service name **MUST NOT** equal the name of an MCP server, global or pod-scoped, and an MCP
    server name **MUST NOT** equal the name of a service. `setup service add`, `setup mcp add` and
    `pod update` (a directory declaring both, or either one against what is kept) **MUST** refuse
    the second name, naming both, and write nothing.
16. `docket pod update` **MUST** record each `services/` file in `applied.lock` as kind `service`,
    so a change to one is drift (`config-format.spec.md`, "Scopes, references and the lockfile").

### Registration

17. `docket setup service add <file>` **MUST** load a `kind: service` document, store it, audit
    `services.add` (name, host and operation count; never an `auth` value) and print the service's
    operations with their access. A name already stored, a name taken by an MCP server or an invalid
    document exits 1 and writes nothing. A `${secret:<name>}` reference whose secret is not stored
    **MUST** produce a warning naming the secret and the header, never failing the command.
18. `docket setup service list` **MUST** print each stored service (name, base URL, operation
    count, auth header and the secret names it references), never an `auth` value; `--json` prints
    the same as an array.
19. `docket setup service remove <name>` **MUST** delete the operator's service and audit
    `services.remove`; an unknown name exits 1.

### The call

20. `call_operation(request) -> ToolOutcome` (`docket.platform.service_http`) **MUST** take a `ServiceRequest`
    carrying the method, the service's `base_url`, a path template, the values for its `{name}`
    parameters, a query mapping, the headers, an optional JSON body and the extra `hosts` the document
    lists. The caller resolves a secret before building the request; `platform` imports nothing from
    `governance`.
21. The method **MUST** be one of `GET`, `POST`, `PUT`, `PATCH`, `DELETE`; any other is refused.
22. The URL **MUST** be the `base_url` (without a trailing slash) followed by the path template with
    each `{name}` replaced by its value percent-encoded with no safe characters, so a value holding
    `/`, `?`, `#` or `..` stays one path segment and is never concatenated raw. A value that is `.` or
    `..` on its own, a `{name}` with no value, and a `{name}` left in the result **MUST** be refused.
    The query mapping is appended encoded, a boolean as `true` or `false`.
23. A body, when given, **MUST** be sent as compact JSON with `Content-Type: application/json`.
24. A 2xx response whose body parses as JSON **MUST** return `ok` with that JSON re-serialised
    compactly; any other 2xx body **MUST** return `ok` with the text, decoded as UTF-8 with
    replacement.
25. A non-2xx response **MUST** return a failed outcome whose `error` names the status code, the method
    and the host and path (never the query), and the head of the body (at most 500 characters).
26. A connection error or a timeout **MUST** return a failed outcome naming the host; nothing raises.

### The perimeter

27. The host of the URL **MUST** be the host of `base_url` or one of `hosts` (compared in lowercase);
    `base_url` **MUST** be `http` or `https` with a host and no embedded credentials. Otherwise the call
    is refused (`refusal="service_not_allowed"`) before any socket is opened.
28. A redirect **MUST NOT** be followed to a host outside that set, or to a scheme that downgrades `https`
    to `http`; the refusal is reported as in Requirement 27. A redirect inside the set is followed.
29. Every address the host resolves to **MUST** be checked before connecting; the call **MUST** connect
    to the address it checked. A private, loopback, link-local, multicast, reserved or unspecified
    address **MUST** be refused (`refusal="service_not_allowed"`) unless the host is listed
    in `hosts` explicitly: being the `base_url` host is not enough. System proxy settings **MUST NOT**
    apply, since a proxy would move the connection past the check.
30. A header name **MUST** be an HTTP token and a header value **MUST NOT** contain CR, LF or NUL; a
    header named `Host`, `Content-Length` or `Transfer-Encoding` **MUST** be refused. A violation is
    refused (`refusal="service_bad_request"`) before any socket is opened.
31. The call **MUST** be bounded in time by `Home.fetch_timeout_s` (the whole call, headers and body)
    and in size by `Home.fetch_max_response_bytes`: a body over the cap is cut at it and the content
    ends with `[truncated: response exceeded <N> bytes]`, so a cut body is returned as text, never as
    JSON.
32. The value of any header named `Authorization`, `Proxy-Authorization`, `Cookie`, or containing
    `key`, `token`, `secret` or `auth`, each word of it, and every value in the request's `secrets`
    **MUST** be replaced by `[REDACTED]` wherever it appears in the outcome's `content` or `error`, so
    a server that echoes the credential back does not hand it to the model.

## Interface Contracts

### Python API

- `docket.kernel.service`: `ServiceConfig`, `Operation`, `OperationParam`, `ServiceRegistry`,
  `secret_names(value)`
- `docket.teams.services`: `ServiceDocument`, `ServiceDocError`, `load_service_document(path)`,
  `load_services(project="")`, `load_pod_services(project)`,
  `add_service(config)`, `remove_service(name)`, `mcp_name_conflict(name)`,
  `service_name_conflict(name)`
- `docket.platform.service_http`: `ServiceRequest`, `call_operation(request)`

### The call

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

### Document

```yaml
kind: service
name: crm
baseUrl: https://api.example.com/v2
auth:
  header: Authorization
  value: Bearer ${secret:crm}
idempotencyHeader: Idempotency-Key
operations:
  - name: get_contact
    method: GET
    path: /contacts/{id}
    params:
      - {name: id, in: path, type: integer}
  - name: create_contact
    method: POST
    path: /contacts
    body: {type: object, properties: {email: {type: string}}, required: [email]}
```

## Examples

### A write declared read

```
$ docket setup service add crm.yaml
Error: crm.yaml: operations.1: operation 'create_contact': POST is always send, not read
```

### A path parameter stays one segment

A request `GET http://127.0.0.1:8123` with `path="/items/{id}"` and `path_params={"id": "../x"}` calls
`/items/..%2Fx`. The same request with `hosts=()` is refused with `service_not_allowed` before
a socket opens; with `hosts=("127.0.0.1",)` it is sent.

## Validation

### Pre-conditions

- The file named to `setup service add` exists and is a mapping

### Post-conditions

- After a refused `add`, `services.json` is exactly as it was
- No stored or exported document contains a resolved secret

### Invariants

- A `${secret:...}` reference is never resolved by a function of this specification
- A service and an MCP server never share a name
- The host of a call is the service's `baseUrl` host or one of its `hosts`, on every redirect
- A private or loopback address is reached only when its host is listed in `hosts`

## Implementation

- `src/docket/kernel/service.py`: the typed config and its rules
- `src/docket/teams/services.py`: the document, the stores, the name rule
- `src/docket/teams/apply/external.py`: the `pod update` planner for `services/`
- `src/docket/interfaces/cli/commands/setup_service.py`: `setup service`
- `src/docket/platform/service_http.py`: `call_operation` and the perimeter
- `tests/integration/platform/test_service_http.py` drives `call_operation` against a loopback
  `http.server`; `tests/unit/platform/test_service_http.py` covers the pure helpers (URL building,
  header checks, address classification, redaction)
