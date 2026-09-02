# Support and deprecation policy

Docket is pre-1.0 personal R&D software. This policy distinguishes code that can receive fixes from
configurations that are merely covered by compatibility tests. The detailed compatibility matrix
is in [COMPATIBILITY.md](COMPATIBILITY.md); security reporting and response targets are in
[SECURITY.md](SECURITY.md).

## Supported versions

| Line | Status | Maintenance provided |
| --- | --- | --- |
| `main` | Supported | Security and maintenance fixes are applied here. |
| older tags | Not supported | No fixes or backports are promised. Upgrade to a current `main` build. |

There are no maintained release branches, no LTS or long-term support line, and no promise to
backport a fix to a published beta tag. A version or platform appearing in
[COMPATIBILITY.md](COMPATIBILITY.md) means its stated boundary is tested; it does not turn that
version into a supported maintenance branch.

## Pre-1.0 changes and deprecations

Before 1.0, interfaces may change as the project learns from real use. For an intentional removal
or incompatible change to a documented public CLI command, configuration key, persisted schema, or
Python API, the normal rule is:

1. announce the deprecation in [CHANGELOG.md](CHANGELOG.md) and the affected beta's release notes;
2. retain the old behavior, or provide a clear migration error, for at least one published beta;
   and
3. document the replacement or migration before removal.

That one-published-beta notice may be shortened when retaining behavior would preserve an actively
exploited vulnerability, unsafe data mutation, or a demonstrably false security boundary. An
exception must be called out in the changelog and release notes with the safe migration. This is a
notice policy, not guaranteed compatibility: beta users should review changes before upgrading.

## Getting help and reporting problems

For reproducible product defects, use the repository's
[bug report template](.github/ISSUE_TEMPLATE/bug_report.yml). General support is community
best-effort; there is no paid support SLA and no separate response-time commitment in this document.

Report vulnerabilities only through [SECURITY.md](SECURITY.md). Its private reporting channels,
acknowledgement target, remediation target, disclosure process, and supported-version statement are
authoritative. This document does not strengthen or duplicate those promises.

Platform notes such as macOS best-effort CI status remain defined in
[COMPATIBILITY.md](COMPATIBILITY.md). They do not override the version support matrix above.
