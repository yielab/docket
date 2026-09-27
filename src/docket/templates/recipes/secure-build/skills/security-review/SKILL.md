---
name: security-review
description: A concrete checklist for reviewing a change for common security defects before approving it.
---

# Security review checklist

Work through each item against the actual diff, not the description of the change. Answer
`APPROVE` only once every applicable item is checked; otherwise answer `REQUEST-CHANGES` and
name the specific item and location.

## Injection points

- Every value that reaches a shell command, SQL query, HTML template, or regular expression
  came from a fixed constant or was escaped/parameterized for that destination.
- No string concatenation builds a command, query, or path from caller-controlled input.
- A new `eval`/`exec`-shaped call (in any language) is justified and its input is not
  attacker-reachable.

## Secrets in the diff

- No literal API key, token, password, or private key appears in the added or changed lines.
- No `.env`, credentials file, or key material is added, renamed into a tracked path, or
  un-ignored.
- A secret-shaped string in a test fixture or example is clearly fake (obviously invalid
  format, or documented as a placeholder), not a real credential.

## Deserialization and parsing

- Untrusted input is deserialized with a safe, schema-bound loader (never a
  pickle-equivalent or a loader that can execute code) for the language in use.
- A new parser or format loader fails closed on malformed input rather than continuing with
  partial state.

## Path traversal and file access

- Every filesystem path built from caller-controlled input is resolved and checked against
  an intended root before use; `..`, absolute paths, and symlink escapes are rejected, not
  merely stripped.
- A new file read/write/delete is scoped to a specific, justified directory, not an
  unrestricted or caller-chosen one.

## Dependency changes

- A new or upgraded dependency is pinned, comes from the expected registry, and its purpose
  matches what the change needs.
- A dependency with known advisories, or one added only for a throwaway script, is flagged
  even if it currently passes.

## Authentication and authorization

- Every new or modified endpoint, command, or tool call re-checks who is allowed to invoke
  it — no code path relies solely on the caller "not knowing" a URL, flag, or tool name.
- A privilege check that existed before the change is not weakened, bypassed, or moved
  after the operation it was meant to guard.
- Session, token, or credential handling introduced by the change fails closed (rejects) on
  an expired, malformed, or missing credential rather than defaulting to allow.

## Closing

State which items were checked and which, if any, could not be verified from the diff alone
(and what would be needed to verify them) before giving the final verdict.
