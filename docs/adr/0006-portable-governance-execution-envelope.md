# ADR 0006 (D-33): The execution envelope and fixture evidence behind the portable-governance claim

**Question:** What execution envelope and fixture evidence are sufficient for the D-27 portable-governance claim?

**Where decided:** Wave 28 triage

## Decision

**One Docket-owned, per-execution envelope must be shared by both adapters.** It receives provider-reported usage before the corresponding foreign tool request can execute, enforces finite cumulative token and tool-call budgets, routes every relevant action through the existing `Runtime.dispatch`/private `dispatch_tool` chokepoint, emits one redacted `tool_call`/`tool_result` pair under the caller's stable identity, preserves the existing hash-chained audit behavior for non-allow decisions, and terminalizes once with a typed result plus `HandoffArtifact`. The common artifact-installed fixture uses a fresh home/workspace and the same scripted scenario table for exclusive tool registration, unknown/native bypass, allow, policy deny, approval deny/grant, over-budget no-mutation, trace/audit identity, and handoff parity. OpenHands uses an ephemeral loopback protocol fake and PydanticAI uses `FunctionModel`; neither hosted credentials nor subscriptions are evidence. Port 8081 is optional canary-only. A2A is not scheduled because the selected coding adapter is in-process; OTLP is not scheduled unless the merged fixture proves JSONL cannot preserve identity. Passing these exact configurations permits only a configuration-scoped claim, never that arbitrary native tools or all framework deployments are governed.
