# Governance

This document describes how Docket is governed today. It is a small personal R&D project, not a
foundation-backed project or a staffed product organization.

## Current maintainership and authority

Docket currently has one active maintainer, `@santiagoyie`, as reflected in
[CODEOWNERS](.github/CODEOWNERS). There is no committee or separate release team.

The active maintainer has final decision authority for the project roadmap, architecture, security
posture, contribution acceptance, and repository administration. The same maintainer has release
authority: deciding when a version is ready, preparing and signing release material, and publishing
it. Discussion can build consensus, but an issue, pull request, or roadmap proposal is not accepted
until the maintainer explicitly accepts it.

Decisions that affect users should be explainable in the relevant issue or pull request and, when
they change durable product direction, in the roadmap or current specification. Contributors can
challenge a decision with new technical evidence through the normal contribution process described
in [CONTRIBUTING.md](CONTRIBUTING.md).

## Becoming a maintainer

Maintainer access is earned through trust and demonstrated project stewardship, not a fixed number
of commits. A candidate should have:

- made sustained contributions across more than one change or release cycle;
- participated constructively in code review and issue triage;
- shown working knowledge of the architecture, test contract, release process, and security model;
- handled private or sensitive information responsibly; and
- enough availability to review changes and help maintain releases.

The current maintainer starts the process with an explicit invitation. The candidate must provide
explicit acceptance before any access or public role changes. The change is then recorded in this
document and [CODEOWNERS](.github/CODEOWNERS), together with the corresponding repository access.
Contribution alone does not automatically grant maintainership.

## Conflicts, conduct, and security

Project disagreements should stay on the issue or pull request where the evidence can be reviewed.
For conduct matters, follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). If the maintainer has a direct
personal or financial conflict, they should disclose it and recuse themselves from making a
substantive recommendation where feasible, requesting review from an uninvolved established
contributor. Because the project currently has only one maintainer, repository or release authority
does not transfer through that request; a new maintainer must first complete the process above.

Do not disclose a vulnerability in a public governance thread. Use the private channels and
disclosure process in [SECURITY.md](SECURITY.md). That policy is the authority for security handling
and its response targets.

## Inactivity and succession

The inactivity trigger is 90 consecutive days with both:

1. no maintainer-authored repository activity, such as a commit, review, issue response, or release;
   and
2. no response after a good-faith attempt to contact the maintainer through the repository's
   documented public contribution channel and the contact route in
   [SECURITY.md](SECURITY.md) when the matter is sensitive.

Reaching the trigger does not automatically appoint anyone or transfer credentials. Contributors
should document the observed inactivity in an issue, keep security details private, and identify a
willing candidate who satisfies the maintainer criteria. If the current owner returns, they can
complete an orderly transfer after the candidate's explicit acceptance and update this document,
CODEOWNERS, and repository permissions in the same transition.

If continued maintenance cannot be transferred to an accepted maintainer, the intended outcome is
to archive the original repository as read-only rather than imply that it remains supported. If the
owner is unavailable and repository transfer or archival cannot be performed, the license still
permits the community to fork; the original repository should be treated as dormant, not as a
community-governed successor.

No successor is currently designated.
