# Service Client Specification

**Version**: 1.1.0
**Status**: Implemented in part: the document, its access rule, its registration and its scopes
(`kernel/service.py`, `teams/services.py`, `docket setup service`, `docket pod update|export`). No
operation is a tool yet and no call is made: the call and its perimeter, and the tools, are
separate work. Requirements 40-41 hold at the gate for any tool named `svc__<service>__<operation>`
(quota) or marked `deletes` (approval); the service tool that sets the mark is separate work.
**Last Updated**: 2026-10-30

## Purpose

A pod reaches an external HTTP service without anyone writing a program for it. A service is a
document: its address, how it authenticates, and the operations a pod may perform on it, each with
the access it needs. docket reads the document, keeps it, and (in later work) turns each operation
into a tool that passes `dispatch_tool` like any other. This specification defines the document and
the rule that decides what an operation may do. It is the declared-service counterpart of the MCP
client (`mcp-client.spec.md`), which reaches a service through a program someone wrote.

## Scope

This specification covers:

- The `kind: service` document and its typed form (`ServiceConfig`, `Operation`)
- The access of an operation and the rule that bounds it by its HTTP method
- Where a service is kept (the operator's file, a pod's `services/` directory) and how it travels
  (`pod update`, `pod export`)
- The rule that a service and an MCP server never share a name
- `docket setup service add|list|remove`
- How writing operations are handled apart: the quota per service and the approval of a `DELETE`

This specification does NOT cover:

- Making a call, resolving a secret, the host perimeter, the size and time bounds (the call)
- Turning an operation into a tool (the tools)
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

### Writes

40. A service's `send` operations **MUST** be counted per service. A policy `limit` with
    `service: <name>` (`security-gates.spec.md`, Policy format v1 requirement 9) **MUST** cover
    every `send` operation of that service, the tools named `svc__<name>__<operation>`, and no
    tool of another service or of none: with `count: 1`, the second send to the service in the
    window is blocked and a send to another service is not. A quota is never per operation.
41. An approval of a `DELETE` operation **MUST** offer `approve_once` and `deny` only; `approve_task`
    sent for it **MUST** be refused (`security-gates.spec.md`, in-turn tool-call gate 19). The tool
    built from a `DELETE` operation **MUST** be marked `deletes`, the field the gate reads; a
    `POST`, `PUT` or `PATCH` keeps the three options.

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

## Interface Contracts

### Python API

- `docket.kernel.service`: `ServiceConfig`, `Operation`, `OperationParam`, `ServiceRegistry`,
  `secret_names(value)`
- `docket.teams.services`: `ServiceDocument`, `ServiceDocError`, `load_service_document(path)`,
  `load_services(project="")`, `load_pod_services(project)`,
  `add_service(config)`, `remove_service(name)`, `mcp_name_conflict(name)`,
  `service_name_conflict(name)`

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

## Validation

### Pre-conditions

- The file named to `setup service add` exists and is a mapping

### Post-conditions

- After a refused `add`, `services.json` is exactly as it was
- No stored or exported document contains a resolved secret

### Invariants

- A `${secret:...}` reference is never resolved by a function of this specification
- A service and an MCP server never share a name

## Implementation

- `src/docket/kernel/service.py`: the typed config and its rules
- `src/docket/teams/services.py`: the document, the stores, the name rule
- `src/docket/teams/apply/external.py`: the `pod update` planner for `services/`
- `src/docket/interfaces/cli/commands/setup_service.py`: `setup service`
