"""docket help — full help text.

Uses raw ANSI escapes via plain print() rather than Rich markup to preserve
literal square-bracketed tokens (`[id]`, `[N]`, `[--debug]`, `[agent-id]`)
that Rich's markup parser would otherwise swallow.

The MODEL POLICY model names are resolved live from the role→model registry.
"""

from __future__ import annotations

from docket.core import models_policy as _mp

_BOLD = "\033[1m"
_GREEN = "\033[0;32m"
_CYAN = "\033[0;36m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def run_help() -> int:
    """Print the full docket help text. Always returns 0."""
    B, G, C, D, R = _BOLD, _GREEN, _CYAN, _DIM, _RESET

    cheap = _mp.resolve_role_model("tester")
    strong = _mp.resolve_role_model("programmer")

    text = f"""
{B}docket — OpenClaw project manager{R}

{B}AGENT TYPES{R}
  {C}Org Specialists{R}     Created by 'docket install' — shared across all projects
                        → manager, knowledge, security
                        → Work across ALL projects (don't create/delete manually)
  {C}Project Pods{R}        Created by 'docket add' — one isolated pod per project
                        → lead + implementer (+ optional reviewer, tester)
                        → Manage with 'docket pod <project>'

  {C}Project Agents{R}      Created by 'docket add' — one per project/codebase
                        → Each has its own workspace, memory, and Telegram group

{B}USAGE{R}
  docket [--debug] <command> [agent-id] [args]
  If agent-id is omitted an interactive picker is shown (fzf or numbered list).

{B}SETUP{R}
  {G}install{R}            Bootstrap OpenClaw + create specialist agents

{B}LIFECYCLE{R}
  {G}list{R}               List all project agents and their status
  {G}add{R}                Add a new project agent (interactive)
  {G}add{R} {D}--from <f>{R}     Provision agent(s) from a YAML/JSON spec (declarative)
  {G}info{R}     [id]      Detailed status for a project
  {G}delete{R}   [id]      Remove a project agent
  {G}maintain{R} [id]      Health check & maintenance (see subcommands below)

{B}MAINTENANCE  (docket maintain [id] <subcommand>){R}
  {G}check{R}              Health check + auto-fix (default)
  {G}clean{R}              Clear memory logs only
  {G}reset{R}              Clear memory + heartbeat
  {G}rebuild{R}            Deep rebuild from .docket-meta.json
  {G}sessions{R}           Archive large/old sessions (>5 MB or >30 days)

{B}TELEGRAM{R}
  {G}wire{R}   [id]        Wire or update a Telegram group binding
  {G}unwire{R} [id]        Remove Telegram binding from a project

{B}CONFIGURATION{R}
  {G}profile{R}  [id] [m]  Pin an agent's model (<provider/model>) or 'default' to
                        follow the role policy; --budget <USD> sets a spending cap
  {G}models{R}             View/change the role→model policy; switch provider presets
  {G}scope{R}    [id] [a]  Manage session scopes for multi-project isolation
  {G}auth{R}     <action>  Configure Claude model auth (subscription or API key)
  {G}keys{R}     <action>  Manage workspace secrets — syncs to all agents

{B}CONTEXT & MEMORY  (docket context [id] <subcommand>){R}
  {G}show{R}               Recent activity, active tasks, stats (default)
  {G}search{R}  <query>    Search indexed memory
  {G}snapshot{R}           Create SNAPSHOT.md for fast agent context
  {G}index{R}              Index memory files for search
  {G}compress{R}           Archive logs older than 30 days
  {G}project{R}            Quick-reference: codebase, stack, decisions

{B}MONITORING{R}
  {G}cost{R}     [id]      Token usage and cost breakdown with budget status
  {G}doctor{R}             System health: gateway, config, drift, budget, runaway
  {G}gates{R}              Exec-approval gates: status / enable / disable (on by default)
  {G}audit{R}    [N]       Recent mutating operations (keys, gates, profile, agents)
  {G}eval{R}               Specialist-role evals: structural checks + live golden tasks

{B}OBSERVABILITY{R}
  {G}trace{R}    <session>  Render one agent-action trace human-readable
  {G}trace tail{R} <proj>   Follow the most-recent session live
  {G}trace export{R} <proj> Export raw JSONL (--since YYYY-MM-DD)
  {G}trace ingest{R} <proj> Ingest daemon session logs into traces
  {G}metrics{R}            Success rate, latency, cost, guardrail trips (--role --window)
  {G}policies list{R}      List installed guardrail policies
  {G}policies init{R}      Install baseline policies (block-destructive, injection, redact)
  {G}policies test{R}      Dry-run policy evaluator on any text
  {G}approve{R}  <token>   Grant a pending HITL approval
  {G}deny{R}     <token>   Deny a pending HITL approval

{B}PODS, QUEUE & WORKFLOWS{R}
  {G}pod{R} <project>          Inspect/manage a project pod (add/remove members)
  {G}pod{R} <project> delegate Queue a task for the pod
  {G}pod{R} <project> queue    Show the pod's task queue
  {G}pod{R} <project> dispatch Run queued tasks through the pod pipeline
  {G}workflow{R} [id]          Manage Lobster YAML pipelines

{B}UTILITIES{R}
  {G}logs{R}      [id]     View memory logs and gateway entries
  {G}edit{R}      [id]     Open workspace files in $EDITOR
  {G}snapshot{R}           JSON dump of all agents, bindings, costs (--output <file>)
  {G}serve{R}              Live JSON endpoint for dashboards (--port 7331 --interval 30)
  {G}completions{R}        Shell completion script — eval "$(docket completions bash|zsh)"
  {G}help{R}               This help message

{B}MODEL POLICY{R}  (default: Anthropic — change with 'docket models preset')
  Each agent role maps to the cheapest adequate model:
  {G}cheap{R}   {cheap}   manager reviewer tester knowledge task
  {G}strong{R}  {strong}  programmer security repo
  'docket models' shows the full role→model table with pricing; 'docket profile <id>'
  pins one agent to any model (incl. opus-class) without changing the policy.

{B}FLAGS{R}
  --debug         Verbose mode — or set DEBUG=1 in env

{B}EXAMPLES{R}
  docket                            # show project list
  docket add                        # add a new project (interactive)
  docket add --from agents.yaml     # provision a fleet from a spec file
  docket doctor                     # full health check
  docket info myproject             # inspect one project
  docket maintain myproject clean   # clear memory logs
  docket profile myproject default  # follow the role policy model
  docket profile myproject anthropic/claude-opus-4-6  # pin a stronger model
  docket profile myproject --budget 5  # set $5 spending cap
  docket context myproject search "auth bug"  # search memory
  docket cost                       # cost breakdown for all agents
  docket pod myproject delegate "Fix login bug"  # queue task for the pod
  docket pod myproject dispatch     # run queued tasks

{B}PATHS{R}
  Workspaces:  ~/.openclaw/workspaces/projects/
  Config:      ~/.openclaw/openclaw.json
  Logs:        /tmp/openclaw/openclaw-YYYY-MM-DD.log
"""
    print(text)
    return 0
