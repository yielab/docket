#!/usr/bin/env bash
# Seed a deterministic fake docket home for golden tests.
# Usage: seed.sh <fake_home_dir>
#
# Creates (under <fake_home>/.openclaw/ -- see run.sh's run_docket() for why
# DOCKET_HOME is still pinned to a directory with that name):
#   fleet.json              — docket's own registry: 2 project agents + 6
#                              specialists, 1 binding
#   docket-models.json      — model policy overrides (empty, uses built-ins)
#   workspaces/projects/myshop/    .docket-meta.json + stub workspace files
#   workspaces/projects/content/   .docket-meta.json + stub workspace files
#   workspaces/programmer/         .docket-meta.json (specialist)
#   workspaces/reviewer/           ...
#   workspaces/tester/             ...
#   workspaces/knowledge/          ...
#   workspaces/security/           ...
#   workspaces/manager/            ...
#
# All timestamps are fixed to 2026-03-05T12:00:00-03:00 for determinism.
#
# CL-C (wave 14): this fixture used to also write an openclaw.json file
# (the pre-P19-7b daemon config format) alongside fleet.json. docket has not
# read openclaw.json since P19-7b deleted the ACL that parsed it -- fleet.json
# has been the only registry this suite (or docket itself) consults since
# P19-6 -- so seeding it was dead weight left behind by that migration, not a
# real fixture requirement. Removed, along with the fake `openclaw` binary
# (tests/golden/fakes/openclaw) that read it back and the unused
# OPENCLAW_DIR env export in run.sh's run_docket().

set -euo pipefail

FAKE_HOME="${1:?usage: seed.sh <fake_home_dir>}"
OC_DIR="$FAKE_HOME/.openclaw"
FIXED_TS="2026-03-05T12:00:00-03:00"

mkdir -p \
  "$OC_DIR/workspaces/projects/myshop" \
  "$OC_DIR/workspaces/projects/content" \
  "$OC_DIR/workspaces/programmer" \
  "$OC_DIR/workspaces/reviewer" \
  "$OC_DIR/workspaces/tester" \
  "$OC_DIR/workspaces/knowledge" \
  "$OC_DIR/workspaces/security" \
  "$OC_DIR/workspaces/manager" \
  "$OC_DIR/traces" \
  "$OC_DIR/policies" \
  "$OC_DIR/approvals"

chmod 700 "$OC_DIR"

# ── fleet.json (docket's own registry, DOCKET_HOME-pinned to $OC_DIR by
# run.sh — see that file's run_docket() for why) ────────────────────────────────
# Agent registration, channel bindings, and gates/isolation flags. Per-agent
# model is deliberately NOT duplicated (see core/fleet.py) -- only the bare
# registration fact.
cat >"$OC_DIR/fleet.json" <<'JSON'
{
  "agents": [
    { "id": "myshop" },
    { "id": "content" },
    { "id": "programmer" },
    { "id": "reviewer" },
    { "id": "tester" },
    { "id": "knowledge" },
    { "id": "security" },
    { "id": "manager" }
  ],
  "bindings": [
    { "agentId": "myshop", "channel": "telegram", "peerKind": "group", "peerId": "-1001234567890" }
  ],
  "defaults": { "model": "anthropic/claude-sonnet-4-6" },
  "security": { "gatesEnabled": false, "isolationEnabled": false }
}
JSON
chmod 600 "$OC_DIR/fleet.json"

# ── docket-models.json (empty policy — uses built-in defaults) ─────────────────
cat >"$OC_DIR/docket-models.json" <<'JSON'
{
  "roles": {},
  "default": "anthropic/claude-sonnet-4-6"
}
JSON
chmod 600 "$OC_DIR/docket-models.json"

# ── project agent: myshop ──────────────────────────────────────────────────────
cat >"$OC_DIR/workspaces/projects/myshop/.docket-meta.json" <<JSON
{
  "kind": "project",
  "type": "repo",
  "name": "My Shop",
  "codebase": "$FAKE_HOME/Sites/myshop",
  "stack": "Docker,git",
  "model": "anthropic/claude-sonnet-4-6",
  "modelSource": "policy",
  "description": "E-commerce site",
  "created": "$FIXED_TS",
  "sessionKey": "agent:myshop:default",
  "projectKey": "default",
  "templateVersion": "3"
}
JSON
chmod 600 "$OC_DIR/workspaces/projects/myshop/.docket-meta.json"

touch "$OC_DIR/workspaces/projects/myshop/SOUL.md"
touch "$OC_DIR/workspaces/projects/myshop/HEARTBEAT.md"
mkdir -p "$OC_DIR/workspaces/projects/myshop/memory"
chmod 700 "$OC_DIR/workspaces/projects/myshop"

# ── project agent: content ─────────────────────────────────────────────────────
cat >"$OC_DIR/workspaces/projects/content/.docket-meta.json" <<JSON
{
  "kind": "project",
  "type": "task",
  "name": "Content Blog",
  "codebase": "",
  "stack": "",
  "model": "anthropic/claude-haiku-4-5",
  "modelSource": "pinned",
  "description": "Blog content generation",
  "created": "$FIXED_TS",
  "sessionKey": "agent:content:blog",
  "projectKey": "blog",
  "budgetUsd": 10,
  "templateVersion": "3"
}
JSON
chmod 600 "$OC_DIR/workspaces/projects/content/.docket-meta.json"

touch "$OC_DIR/workspaces/projects/content/SOUL.md"
touch "$OC_DIR/workspaces/projects/content/HEARTBEAT.md"
mkdir -p "$OC_DIR/workspaces/projects/content/memory"
chmod 700 "$OC_DIR/workspaces/projects/content"

# ── specialist agents ──────────────────────────────────────────────────────────
for role in programmer reviewer tester knowledge security manager; do
  model="anthropic/claude-sonnet-4-6"
  [[ "$role" =~ ^(reviewer|tester|knowledge|manager)$ ]] && model="anthropic/claude-haiku-4-5"

  cat >"$OC_DIR/workspaces/$role/.docket-meta.json" <<JSON
{
  "kind": "specialist",
  "role": "$role",
  "name": "$role",
  "model": "$model",
  "modelSource": "policy",
  "created": "$FIXED_TS",
  "templateVersion": "3"
}
JSON
  chmod 600 "$OC_DIR/workspaces/$role/.docket-meta.json"
  touch "$OC_DIR/workspaces/$role/SOUL.md"
  chmod 700 "$OC_DIR/workspaces/$role"
done

# ── fake codebase dirs ─────────────────────────────────────────────────────────
mkdir -p "$FAKE_HOME/Sites/myshop"
touch "$FAKE_HOME/Sites/myshop/Dockerfile"
touch "$FAKE_HOME/Sites/myshop/.git"
