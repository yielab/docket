#!/usr/bin/env bash
# schema.sh — single source of truth for the .docket-meta.json field set.
#
# AGENT_SCHEMA is an ordered array of field descriptors. Each entry is a
# tab-separated 4-tuple:
#
#   name<TAB>type<TAB>enum_values_or_dash<TAB>sync_class
#
# type        : string | number | bool | enum
# enum values : pipe-separated list (e.g. "policy|pinned"), or "-" for non-enum
# sync_class  : synced  — mirrored to openclaw.json; docket doctor checks these
#               local   — docket-only state; never expected in openclaw.json
#
# This array is consumed by:
#   meta_set     (validation — lib/helpers/json.sh)
#   doctor       (drift detection — lib/commands/doctor.sh)
#   CDD-5 linter (spec↔code field-set equality — scripts/spec-coverage.sh)
#
# To add a field: append a row here AND add it to specs/data/docket-meta.spec.md.
# The unit test "schema table ↔ spec field-set equality" will catch any mismatch.

AGENT_SCHEMA=(
  #  name            type    enum / -                      sync_class
  "kind	enum	project|specialist	local"
  "role	string	-	local"
  "type	enum	repo|task	local"
  "name	string	-	local"
  "codebase	string	-	local"
  "stack	string	-	local"
  "model	string	-	synced"
  "modelSource	enum	policy|pinned	local"
  "description	string	-	local"
  "created	string	-	local"
  "sessionKey	string	-	synced"
  "projectKey	string	-	local"
  "budgetUsd	number	-	local"
  "paused	bool	-	local"
  "pausedReason	string	-	local"
  "templateVersion	string	-	local"
)

# Return the descriptor for a given field name, or empty string if unknown.
schema_field() {
  local name="$1"
  local entry
  for entry in "${AGENT_SCHEMA[@]}"; do
    local fname; fname=$(printf '%s' "$entry" | cut -f1)
    if [[ "$fname" == "$name" ]]; then
      printf '%s' "$entry"
      return 0
    fi
  done
  return 1
}

# Print all field names from the schema table, one per line.
schema_field_names() {
  local entry
  for entry in "${AGENT_SCHEMA[@]}"; do
    printf '%s\n' "$entry" | cut -f1
  done
}

# Print all fields with sync_class == "synced", one per line.
schema_synced_fields() {
  local entry
  for entry in "${AGENT_SCHEMA[@]}"; do
    local sc; sc=$(printf '%s' "$entry" | cut -f4)
    if [[ "$sc" == "synced" ]]; then
      printf '%s\n' "$entry" | cut -f1
    fi
  done
}
