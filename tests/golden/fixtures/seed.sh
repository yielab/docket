#!/usr/bin/env bash
# Seed a deterministic fake docket home for golden tests.
# Usage: seed.sh <fake_home_dir>
#
# Creates (under <fake_home>/.docket/ -- see run.sh's run_docket() for why
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
# fleet.json is the only registry this suite (or docket itself) consults.

set -euo pipefail

FAKE_HOME="${1:?usage: seed.sh <fake_home_dir>}"
STATE_DIR="$FAKE_HOME/.docket"
FIXED_TS="2026-03-05T12:00:00-03:00"

mkdir -p \
  "$STATE_DIR/workspaces/projects/myshop" \
  "$STATE_DIR/workspaces/projects/content" \
  "$STATE_DIR/workspaces/programmer" \
  "$STATE_DIR/workspaces/reviewer" \
  "$STATE_DIR/workspaces/tester" \
  "$STATE_DIR/workspaces/knowledge" \
  "$STATE_DIR/workspaces/security" \
  "$STATE_DIR/workspaces/manager" \
  "$STATE_DIR/traces" \
  "$STATE_DIR/policies" \
  "$STATE_DIR/approvals"

chmod 700 "$STATE_DIR"

# ── fleet.json (docket's own registry, DOCKET_HOME-pinned to $STATE_DIR by
# run.sh — see that file's run_docket() for why) ────────────────────────────────
# Agent registration, channel bindings, and gates/isolation flags. Per-agent
# model is deliberately NOT duplicated (see core/fleet.py) -- only the bare
# registration fact.
cat >"$STATE_DIR/fleet.json" <<'JSON'
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
chmod 600 "$STATE_DIR/fleet.json"

# ── docket-models.json (empty policy — uses built-in defaults) ─────────────────
cat >"$STATE_DIR/docket-models.json" <<'JSON'
{
  "roles": {},
  "default": "anthropic/claude-sonnet-4-6"
}
JSON
chmod 600 "$STATE_DIR/docket-models.json"

# ── project agent: myshop ──────────────────────────────────────────────────────
cat >"$STATE_DIR/workspaces/projects/myshop/.docket-meta.json" <<JSON
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
chmod 600 "$STATE_DIR/workspaces/projects/myshop/.docket-meta.json"

touch "$STATE_DIR/workspaces/projects/myshop/SOUL.md"
touch "$STATE_DIR/workspaces/projects/myshop/HEARTBEAT.md"
mkdir -p "$STATE_DIR/workspaces/projects/myshop/memory"
chmod 700 "$STATE_DIR/workspaces/projects/myshop"

# ── project agent: content ─────────────────────────────────────────────────────
cat >"$STATE_DIR/workspaces/projects/content/.docket-meta.json" <<JSON
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
chmod 600 "$STATE_DIR/workspaces/projects/content/.docket-meta.json"

touch "$STATE_DIR/workspaces/projects/content/SOUL.md"
touch "$STATE_DIR/workspaces/projects/content/HEARTBEAT.md"
mkdir -p "$STATE_DIR/workspaces/projects/content/memory"
chmod 700 "$STATE_DIR/workspaces/projects/content"

# ── specialist agents ──────────────────────────────────────────────────────────
for role in programmer reviewer tester knowledge security manager; do
  model="anthropic/claude-sonnet-4-6"
  [[ "$role" =~ ^(reviewer|tester|knowledge|manager)$ ]] && model="anthropic/claude-haiku-4-5"

  cat >"$STATE_DIR/workspaces/$role/.docket-meta.json" <<JSON
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
  chmod 600 "$STATE_DIR/workspaces/$role/.docket-meta.json"
  touch "$STATE_DIR/workspaces/$role/SOUL.md"
  chmod 700 "$STATE_DIR/workspaces/$role"
done

# ── fake codebase dirs ─────────────────────────────────────────────────────────
mkdir -p "$FAKE_HOME/Sites/myshop"
touch "$FAKE_HOME/Sites/myshop/Dockerfile"
touch "$FAKE_HOME/Sites/myshop/.git"
