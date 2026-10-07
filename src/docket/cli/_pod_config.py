"""The pod configuration commands.
Holds config, validate, pipeline, roles, policies, plugins and recipes."""

from __future__ import annotations

import typer


def cmd_pipeline(ctx: typer.Context) -> None:
    """Validate, plan, and run a docket-native pipeline -- the one dialect
    docket actually executes.

    A pipeline file declares a pod's hop order, gates, and rework edges
    instead of relying on the built-in default order.

    Subcommands:
      validate <file>   pure structural validation -- no project involved,
                         nothing dispatched. Checks step ids are unique, each
                         step has exactly one of role/agent, gate shapes are
                         well-formed, and rework edges point at an earlier
                         step id.
      plan <project>    [--file <path>]. Resolves the pipeline against a
                         project's actual pod roster and prints the plan --
                         the exact function `run`/`docket pod <p> dispatch`
                         use internally, not a second pretty-printer. Never
                         executes anything or spends tokens. Without --file,
                         resolves the pod's zero-migration default order
                         (lead -> implementer -> reviewer -> tester,
                         whichever roles the pod has).
      run <project>     [--file <path>] [--resume] [--timeout <seconds>]
                         [--var key=value]... [--follow]. Dispatches a
                         project's pod through the given (or default)
                         pipeline -- delegates to the exact same executor as
                         `docket pod <project> dispatch`, so it is equally
                         budget-gated, verify/Reviewer/Tester-gated, traced,
                         and recorded in `docket runs`. --resume/--timeout
                         behave identically to pod dispatch. Repeatable --var
                         key=value supplies the pipeline's variable
                         namespace (the same one a webhook dispatch resolves
                         from its JSON body); a step's own `instructions` may
                         reference `${key}`, and a missing `required`
                         variable or an unresolved `${key}` reference
                         refuses the run before any hop. --follow tails the
                         run's trace events live in the foreground (Ctrl-C
                         stops watching, not the dispatch itself, which
                         keeps running).

    Pipeline file schema (YAML or JSON; unknown keys rejected): `name`
    (required), `description`, `variables` (a name->{default, description,
    required} map, resolved at dispatch time against --var/a webhook body);
    `steps`: each has `id` (unique), exactly one of `role` (a role-archetype
    slug) or `agent` (a specific member id), optional `retries`, `timeout`
    (seconds), optional `instructions` (overrides the target role's own hop
    instruction for this step; may reference `${var}`), optional `gate`, or
    a `parallel` list of child steps (one nesting level). `gate.type`:
    `mechanical` (a `command`, or null to defer to the target's own
    verifyCmd), `verdict` (a `pattern` regex, `passValues`, optional
    `rework: {to, when, maxCycles}` edge back to an earlier step), or
    `approval` (a human sign-off message).

    A pod with no pipeline file runs the built-in default order -- declaring
    a pipeline is opt-in. `archetype` references inside a step are
    shape-validated only, never checked against the live role registry. See
    specs/functional/pipeline-format.spec.md."""
    from docket.cli._pipeline import run_pipeline

    args = list(ctx.args)
    sub = args[0] if args else None
    raise typer.Exit(run_pipeline(sub, args[1:]))


def cmd_roles(ctx: typer.Context) -> None:
    """Manage declarative role archetypes: list/show/add/validate.

    A role archetype is the data-driven definition behind every pod role
    (lead, implementer, reviewer, tester, and the blueprint-only roles
    researcher, analyst, writer, critic, operator, monitor) -- SOUL/AGENTS
    templates, model class, gate contract, token budget -- not a hardcoded
    branch, so `docket pod <p> add <role>` accepts any name in this registry.

    Subcommands:
      list (default)   all archetypes (built-in + user-defined) with source,
                        scope, model class, gate, and description
      show <name>      the full wire-format definition (YAML, falling back
                        to JSON if PyYAML is missing) -- name, version, scope
                        (org|pod), modelClass (cheap|strong), soulTemplate,
                        agentsTemplate, gateContract
                        (none|verdict|mechanical|approval), toolProfile,
                        tokenBudget, hopInstruction (this role's hop-message
                        instruction; unset means "generate one from
                        gateContract" for a gated role)
      add <file.yaml>  registers a new archetype from a standalone YAML file
                        into the user overlay (`~/.docket/docket-roles.json`)
                        -- built-ins are never edited, only shadowed by name
      validate [file]  structural field validation (closed enums, name
                        regex, non-blank templates) plus a dry-run render of
                        both templates against a representative variable set
                        -- catches a template referencing an unknown `${var}`
                        before add persists it. With no file argument,
                        validates every entry in the merged live registry
                        instead.

    Built-ins and the 6-role starter library are Python literals, never
    loaded from files; a user archetype in `~/.docket/docket-roles.json`
    overlays by name, and a malformed overlay entry is skipped rather than
    crashing a live fleet. See specs/functional/role-archetypes.spec.md."""
    from docket.cli._roles import run_roles

    args = list(ctx.args)
    sub = args[0] if args else None
    raise typer.Exit(run_roles(sub, args=args[1:]))


def cmd_config(
    ctx: typer.Context,
    sub: str = typer.Argument(..., help="explain <agent-id> [--json]"),
) -> None:
    """Read-only inspection of an agent's effective configuration.

    Subcommands:
      explain <agent-id> [--json]  The configuration a real dispatch turn would
                        actually use for this agent, with the source that set
                        each value: resolved model + endpoint (policy/pinned);
                        the composed system prompt's sections with their bytes
                        and fit status (full/truncated/omitted); tools after
                        role denial, plus configured MCP servers; the
                        guardrail policies that apply to this role; the
                        effective pipeline and its source (bound
                        pipeline/blueprint/built-in default); and, for a pod
                        member, the pod's dispatch settings (budgetUsd,
                        maxReworkCycles, turnTimeoutS, verifyTimeoutS,
                        approvalMode, allowCommands) with each key's
                        set/default source. Composes existing resolvers only
                        -- writes nothing, adds no new configuration surface.
                        See specs/data/cli-json-shapes.spec.md."""
    from docket.cli import _config

    _config.dispatch(sub, list(ctx.args))


def cmd_validate(target: str | None = typer.Argument(None)) -> None:
    """Validate role, pipeline, policy, and pod configuration documents.

    With no argument, validates `<cwd>/.docket` if it exists, else the current
    directory. A directory argument validates every `roles/*.yaml|yml|json`,
    `policies/*.yaml|yml|json`, `pipeline.yaml`, and `pod.yaml` found under it;
    a file argument validates that one file. Prints one line per file -- `ok
    <file> (<kind> <name>)` or its error -- with invalid files listed first,
    plus a `note:` line for a file loaded without a top-level `kind:` key.
    Exits 1 if any file is invalid."""
    from docket.cli._validate import run_validate

    raise typer.Exit(run_validate([target] if target else []))


def cmd_plugins(ctx: typer.Context) -> None:
    """List predicate plugins an operator has applied.

    Subcommand: `list [--pod <p>]` prints every predicate a policy's `when:
    {plugin: ...}` can reach -- global (`~/.docket/plugins/`) then that
    pod's own `config/plugins/`, each with its scope, file and sha256.
    Docket never loads a plugin from a codebase; `docket pod <p> apply` is
    what copies a recipe's `plugins/*.py` into pod scope."""
    from docket.cli._plugins import run_plugins

    raise typer.Exit(run_plugins(list(ctx.args)))


def cmd_recipes(ctx: typer.Context) -> None:
    """List and inspect the recipe library.

    Subcommands: `list [--json]` prints every recipe reachable by name --
    the operator's own `~/.docket/recipes/<name>/` before the shipped
    library, nearest scope wins -- with its derived kind (team/policies/
    pipeline/mixed) and description. `show <name|dir> [--json]` prints one
    recipe's description, scope, directory, derived summary, and README
    body. Installs, removes, or fetches nothing; `docket pod <p> apply`/
    `docket init --recipe` remain the only writers."""
    from docket.cli._recipes import run_recipes

    raise typer.Exit(run_recipes(list(ctx.args)))


def cmd_policies(ctx: typer.Context) -> None:
    """Manage tool-approval policies.

    Manages declarative guardrail policies evaluated on each agent turn.

    Subcommands: `list` installed policies; `show <name>` prints one
    policy's JSON; `init` copies the 6 baseline templates
    (block-destructive, prompt-injection, secret-pii-redact, and the three
    high-risk-action-class policies: high-risk-payment, high-risk-deploy,
    high-risk-credentials); `validate [id|file.json]` schema-checks one (or
    every) installed policy, including that its regex compiles; `test <hook>
    <role> <text> [--tool <name>]` dry-runs the evaluator, emitting no
    traces. Valid `<hook>` values for `test` are pre_input, pre_tool_call,
    and pre_output -- a policy can fire at enqueue time, before a tool call,
    or on a hop's output. For pre_tool_call, `--tool` (default `bash`) names
    the built-in tool being simulated: an exec tool is judged by the command
    classifier plus the policy hook, exactly like the live gate; any other
    kind is judged by the policy hook alone, because the live gate
    classifies exec commands only.

    A policy file that fails validation is never silently skipped: every
    call it could have governed fails closed (`block`, attributed to the
    file) until it is fixed or removed, and `docket doctor` reports it."""
    from docket.cli._policies import run_policies

    args = list(ctx.args)
    sub = args[0] if args else None
    raise typer.Exit(run_policies(sub, args=args[1:]))
