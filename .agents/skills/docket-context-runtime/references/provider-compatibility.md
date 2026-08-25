# Provider and gateway compatibility

Read this when changing model selection, endpoint resolution, hosted gateways, credentials, or
gateway-derived context and usage.

Treat the coding harness and the model transport as independent axes. Codex, Claude Code, and
OpenCode consume repository instructions; Docket's runtime still sends its own model request.

For each claimed provider, verify the public configuration path and the actual request boundary:

- resolved base URL and the exact nested model id sent on the wire;
- bearer credential precedence without persisting or logging secret values;
- non-streaming Chat Completions messages, advertised function tools, and tool-result replay;
- usage fields Docket actually records, plus context/output limits for the exact registered model;
- top-level and in-choice error shapes, HTTP classification, retry ownership, and `Retry-After`;
- any required routing headers/options, explicitly marking unsupported surfaces.

Test at least two providers together without a process-wide endpoint override. Begin from the
public key/provider operation and keep the fake only at the HTTP boundary. Distinguish one Docket
request, Docket's external retry attempts, and any gateway-internal routing/failover; only attempts
Docket actually transports count as its backend calls.

Model availability and pricing change independently of protocol compatibility. Prefer a provider's
stable router or catalog lookup over a dated curated list, and label live remote canaries opt-in
with an explicit request/cost budget. Preserve `unknown_window` when exact metadata is absent.
