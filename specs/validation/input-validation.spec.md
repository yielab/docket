# Input Validation Specification

**Version**: 1.0.0
**Status**: Complete
**Last Updated**: 2024-01-20

## Purpose

This specification defines all input validation rules for rack CLI commands to ensure data integrity, security, and proper error handling.

## Validation Categories

### 1. Agent ID Validation

**Field**: agent-id
**Used By**: add, info, delete, reset, profile, scope, workflow, repair

**Rules**:
- **MUST** match pattern: `^[a-z0-9][a-z0-9-]*[a-z0-9]$`
- **MUST** be between 3 and 50 characters
- **MUST NOT** contain consecutive hyphens
- **MUST NOT** be a reserved word
- **MUST** be unique (for creation)

**Reserved Words**:
- system, rack, openclaw, manager
- admin, root, daemon, service
- config, settings, help, version

**Validation Function**:
```bash
validate_agent_id() {
    local id="$1"
    local check_exists="${2:-false}"

    # Check if empty
    if [[ -z "$id" ]]; then
        return 1
    fi

    # Check length
    if [[ ${#id} -lt 3 ]] || [[ ${#id} -gt 50 ]]; then
        error "Agent ID must be 3-50 characters"
        return 1
    fi

    # Check pattern
    if ! [[ "$id" =~ ^[a-z0-9][a-z0-9-]*[a-z0-9]$ ]]; then
        error "Agent ID must be lowercase alphanumeric with dashes"
        return 1
    fi

    # Check consecutive hyphens
    if [[ "$id" == *"--"* ]]; then
        error "Agent ID cannot contain consecutive hyphens"
        return 1
    fi

    # Check reserved words
    local reserved=("system" "rack" "openclaw" "manager" "admin" "root")
    for word in "${reserved[@]}"; do
        if [[ "$id" == "$word" ]]; then
            error "Agent ID '$id' is reserved"
            return 1
        fi
    done

    # Check existence if requested
    if [[ "$check_exists" == "true" ]]; then
        if [[ -d "$WORKSPACES_DIR/projects/$id" ]]; then
            error "Agent '$id' already exists"
            return 1
        fi
    fi

    return 0
}
```

### 2. Path Validation

**Field**: codebase-path, file-path
**Used By**: add, workflow

**Rules**:
- **MUST** be absolute path or start with ~
- **MUST** exist (for codebase)
- **MUST** be readable
- **MUST NOT** be system directory
- **MUST** resolve symlinks

**Forbidden Paths**:
- /, /bin, /sbin, /usr, /lib, /lib64
- /etc, /boot, /dev, /proc, /sys
- /root, /var/log

**Validation Function**:
```bash
validate_path() {
    local path="$1"
    local must_exist="${2:-true}"
    local type="${3:-dir}"  # dir or file

    # Expand tilde
    path="${path/#\~/$HOME}"

    # Convert to absolute
    if [[ ! "$path" = /* ]]; then
        path="$(pwd)/$path"
    fi

    # Resolve symlinks
    if [[ -L "$path" ]]; then
        path=$(readlink -f "$path")
    fi

    # Check existence
    if [[ "$must_exist" == "true" ]]; then
        if [[ "$type" == "dir" ]] && [[ ! -d "$path" ]]; then
            error "Directory not found: $path"
            return 1
        fi
        if [[ "$type" == "file" ]] && [[ ! -f "$path" ]]; then
            error "File not found: $path"
            return 1
        fi
    fi

    # Check readability
    if [[ "$must_exist" == "true" ]] && [[ ! -r "$path" ]]; then
        error "Permission denied: $path"
        return 1
    fi

    # Check forbidden paths
    local forbidden=("/" "/bin" "/sbin" "/usr" "/lib" "/etc" "/boot")
    for forbid in "${forbidden[@]}"; do
        if [[ "$path" == "$forbid" ]]; then
            error "Cannot use system directory: $path"
            return 1
        fi
    done

    echo "$path"
    return 0
}
```

### 3. Model Validation

**Field**: model, profile
**Used By**: add, profile, model

**Rules**:
- **MUST** be valid model name or profile
- **MUST** exist in MODEL_PROFILES
- Case insensitive matching

**Valid Profiles**:
- economy → claude-haiku-4-5
- standard → claude-sonnet-4-6
- premium → claude-opus-4-6

**Validation Function**:
```bash
validate_model() {
    local input="$1"
    local input_lower=$(echo "$input" | tr '[:upper:]' '[:lower:]')

    # Check profile aliases
    case "$input_lower" in
        economy|eco)
            echo "claude-haiku-4-5"
            return 0
            ;;
        standard|std)
            echo "claude-sonnet-4-6"
            return 0
            ;;
        premium|prem)
            echo "claude-opus-4-6"
            return 0
            ;;
    esac

    # Check exact model names
    local valid_models=(
        "claude-haiku-4-5"
        "claude-sonnet-4-6"
        "claude-opus-4-6"
        "gpt-4"
        "gpt-3.5-turbo"
    )

    for model in "${valid_models[@]}"; do
        if [[ "$input_lower" == "$model" ]]; then
            echo "$model"
            return 0
        fi
    done

    error "Invalid model: $input"
    error "Valid options: economy, standard, premium"
    return 1
}
```

### 4. Numeric Validation

**Field**: level, period, timeout
**Used By**: reset, cost, various

**Rules**:
- **MUST** be positive integer
- **MUST** be within allowed range
- **MUST NOT** have leading zeros

**Ranges**:
- Reset level: 1-3
- Cost period: 1-365 days
- Timeout: 1-3600 seconds

**Validation Function**:
```bash
validate_number() {
    local value="$1"
    local min="$2"
    local max="$3"
    local name="${4:-value}"

    # Check if numeric
    if ! [[ "$value" =~ ^[0-9]+$ ]]; then
        error "$name must be a number"
        return 1
    fi

    # Check leading zeros
    if [[ "$value" =~ ^0[0-9]+$ ]]; then
        error "$name cannot have leading zeros"
        return 1
    fi

    # Convert to integer for comparison
    local num=$((value))

    # Check range
    if [[ $num -lt $min ]] || [[ $num -gt $max ]]; then
        error "$name must be between $min and $max"
        return 1
    fi

    echo "$num"
    return 0
}
```

### 5. Session Key Validation

**Field**: session-key, project-key
**Used By**: scope

**Rules**:
- **MUST** follow format: `agent:<id>:<project>`
- **MUST** have valid agent ID component
- **MUST** have valid project component
- Project **MUST** be alphanumeric + dash
- **MUST NOT** exceed 100 characters total

**Validation Function**:
```bash
validate_session_key() {
    local key="$1"

    # Check format
    if ! [[ "$key" =~ ^agent:[^:]+:[^:]+$ ]]; then
        error "Session key must follow format: agent:<id>:<project>"
        return 1
    fi

    # Extract components
    local agent_id=$(echo "$key" | cut -d: -f2)
    local project=$(echo "$key" | cut -d: -f3)

    # Validate agent ID
    if ! validate_agent_id "$agent_id"; then
        return 1
    fi

    # Validate project component
    if ! [[ "$project" =~ ^[a-z0-9][a-z0-9-]*[a-z0-9]$ ]]; then
        error "Project key must be alphanumeric with dashes"
        return 1
    fi

    # Check total length
    if [[ ${#key} -gt 100 ]]; then
        error "Session key too long (max 100 characters)"
        return 1
    fi

    return 0
}
```

### 6. Command Action Validation

**Field**: action
**Used By**: scope, workflow, team, keys

**Rules**:
- **MUST** be from allowed action list
- Case sensitive
- **MUST** have required arguments

**Actions by Command**:
- scope: get, set, reset
- workflow: create, list, show, delete, run
- team: init, status, assign, sync
- keys: list, set, remove, sync

**Validation Function**:
```bash
validate_action() {
    local command="$1"
    local action="$2"
    shift 2
    local args=("$@")

    case "$command" in
        scope)
            case "$action" in
                get)
                    return 0
                    ;;
                set)
                    if [[ ${#args[@]} -lt 1 ]]; then
                        error "scope set requires a project key"
                        return 1
                    fi
                    ;;
                reset)
                    return 0
                    ;;
                *)
                    error "Invalid scope action: $action"
                    error "Valid actions: get, set, reset"
                    return 1
                    ;;
            esac
            ;;
        workflow)
            case "$action" in
                create|delete|show|run)
                    if [[ ${#args[@]} -lt 1 ]]; then
                        error "workflow $action requires a name"
                        return 1
                    fi
                    ;;
                list)
                    return 0
                    ;;
                *)
                    error "Invalid workflow action: $action"
                    return 1
                    ;;
            esac
            ;;
    esac

    return 0
}
```

### 7. API Key Validation

**Field**: api-key
**Used By**: keys

**Rules**:
- **MUST** match provider's key format
- **MUST NOT** contain whitespace
- **MUST NOT** be empty
- **SHOULD** validate checksum if applicable

**Provider Formats**:
- Anthropic: `sk-ant-api[0-9]{2}-[a-zA-Z0-9-_]{48}`
- OpenAI: `sk-[a-zA-Z0-9]{48}`
- Google: `AIza[a-zA-Z0-9-_]{35}`

**Validation Function**:
```bash
validate_api_key() {
    local provider="$1"
    local key="$2"

    # Check not empty
    if [[ -z "$key" ]]; then
        error "API key cannot be empty"
        return 1
    fi

    # Check no whitespace
    if [[ "$key" =~ [[:space:]] ]]; then
        error "API key cannot contain whitespace"
        return 1
    fi

    # Provider-specific validation
    case "$provider" in
        anthropic)
            if ! [[ "$key" =~ ^sk-ant-api[0-9]{2}-[a-zA-Z0-9-_]{48}$ ]]; then
                warn "Key doesn't match expected Anthropic format"
            fi
            ;;
        openai)
            if ! [[ "$key" =~ ^sk-[a-zA-Z0-9]{48}$ ]]; then
                warn "Key doesn't match expected OpenAI format"
            fi
            ;;
        google)
            if ! [[ "$key" =~ ^AIza[a-zA-Z0-9-_]{35}$ ]]; then
                warn "Key doesn't match expected Google format"
            fi
            ;;
    esac

    return 0
}
```

## Sanitization Rules

### Shell Command Injection Prevention

```bash
sanitize_for_shell() {
    local input="$1"

    # Remove dangerous characters
    input="${input//[\$\`\\]/}"

    # Escape remaining special chars
    printf '%q' "$input"
}
```

### JSON Value Escaping

```bash
escape_json_value() {
    local value="$1"

    # Escape special JSON characters
    value="${value//\\/\\\\}"     # Backslash
    value="${value//\"/\\\"}"     # Quote
    value="${value//	/\\t}"      # Tab
    value="${value//
/\\n}"                          # Newline
    value="${value//\r/\\r}"      # Carriage return

    echo "$value"
}
```

### Path Traversal Prevention

```bash
prevent_path_traversal() {
    local path="$1"
    local base="${2:-$WORKSPACES_DIR}"

    # Resolve to absolute path
    path=$(realpath "$path" 2>/dev/null || echo "$path")

    # Check if path is within base
    if [[ "$path" != "$base"* ]]; then
        error "Path traversal detected"
        return 1
    fi

    echo "$path"
}
```

## Error Messages

### Standard Error Format

```bash
validation_error() {
    local field="$1"
    local value="$2"
    local requirement="$3"

    echo "[ERROR] Validation failed for $field"
    echo "        Value: $value"
    echo "        Requirement: $requirement"
    echo "        Use 'rack help' for usage information"
}
```

### User-Friendly Messages

| Validation | Error Message | Suggestion |
|------------|---------------|------------|
| Agent ID format | "Agent ID must be lowercase alphanumeric with dashes" | "Example: my-project-1" |
| Path not found | "Directory not found: /path" | "Check path exists and is readable" |
| Invalid model | "Invalid model: gpt-5" | "Use: economy, standard, or premium" |
| Number range | "Level must be between 1 and 3" | "Use 1 for light, 2 for deep, 3 for complete" |

## Testing Validation

### Unit Tests

```bash
#!/usr/bin/env bash
# tests/unit/test-validation.sh

test_agent_id_validation() {
    # Valid IDs
    assert_valid "test-agent-1" "valid ID with dashes"
    assert_valid "abc123" "valid alphanumeric"

    # Invalid IDs
    assert_invalid "" "empty ID"
    assert_invalid "a" "too short"
    assert_invalid "Test-Agent" "uppercase letters"
    assert_invalid "test--agent" "consecutive dashes"
    assert_invalid "-test" "starts with dash"
    assert_invalid "test-" "ends with dash"
    assert_invalid "system" "reserved word"
}

test_path_validation() {
    # Valid paths
    assert_valid "/home/user/project" "absolute path"
    assert_valid "~/projects/test" "tilde expansion"

    # Invalid paths
    assert_invalid "/" "root directory"
    assert_invalid "/etc" "system directory"
    assert_invalid "/nonexistent" "path doesn't exist"
}
```

## Performance Considerations

### Validation Timing

- Agent ID: < 1ms
- Path validation: < 10ms (with stat check)
- Model validation: < 1ms
- Session key: < 1ms
- API key format: < 5ms

### Caching

```bash
# Cache validation results for repeated checks
declare -A VALIDATION_CACHE

cached_validate() {
    local key="$1:$2"

    if [[ -n "${VALIDATION_CACHE[$key]:-}" ]]; then
        return "${VALIDATION_CACHE[$key]}"
    fi

    # Perform validation
    validate_"$1" "$2"
    local result=$?

    VALIDATION_CACHE[$key]=$result
    return $result
}
```

## Changelog

### Version 1.0.0 (2024-01-20)
- Complete input validation specification
- All field types covered
- Sanitization rules defined
- Error message standards
- Performance requirements