# Specs truth pass: worker packet (2026-10-22, before Phase 46)

One worker owns **one spec file**. The goal: the spec states what the code does today, carries no
history, and stays true when Phase 46 (ADR 0030) moves the code, because its requirements do not
depend on where the code lives.

Base: `plan/phase-46-structure` at or after `2ed1cce5` (specs no longer carry a `## Changelog`).
Evidence from the 2026-10-22 audit: `internal-docs/audits/specs-audit-2026-10-22.md` (verified) and
`internal-docs/audits/specs-2026-10-22/audit-*.md` (the per-spec annexes, **not verified**: treat
every annex claim as a lead to check, never as a fact).

## What you change, in your spec only

1. **Make it true.** Check every requirement, Status sentence, example and interface entry against
   the code with targeted `rg` (the shell `grep` is ripgrep and skips ignored files). When the spec
   and the code disagree, the spec is corrected to the code. Never change code. If the code looks
   wrong (a reader with no writer, a dead function, two sources that disagree), do not "fix" the
   spec to hide it: keep the requirement true to today's code and list it under "Code defects".
2. **Remove history.** No card ids (`P45-3`, `W116-4`, `Wave 71`), phase or ROADMAP references used
   as narration, "was false until", "since Phase N", "(added in 2.4.0)", "fixed", "no longer",
   "used to". A sentence about a behaviour that no longer exists is deleted. The Status line says the
   state in at most three lines. Keep an ADR or decision id only where the requirement's reason is
   that decision (`(ADR 0024)`), once.
3. **Make it independent of the path.**
   - Purpose, Scope, Status, Requirements and Examples name **behaviour and public names**, never a
     source path (`core/x.py`, `edges/...`, `cli/...`, `serve.py`, `config.py`) and never a private
     symbol (`_foo`).
   - Public names stay: CLI commands and flags, HTTP routes and JSON keys, environment variables,
     files under `DOCKET_HOME`, trace event names, audit actions, config keys and `kind:` documents,
     the `docket_runtime` facade, and module names a user or operator types (`python -m docket.jail`,
     `docket.plugins`). Public Python functions and classes may be named without their module.
   - Add one last section, `## Implementation`, that maps the names the spec uses to where they live
     today, one bullet per module: ``- `src/docket/core/trace.py`: `trace_event`, `EVENT_TYPES` ``.
     This is the only place a path appears; the Phase 46 codemod rewrites this section and nothing
     else.
4. **Do not pre-apply Phase 46.** Where the spec states something Phase 46 will change on purpose
   (pod settings in the Lead's `.docket-meta.json`, the task record's flat shape, test lanes by
   directory, `SUBJECT`, the docket-runtime build hook), keep today's truth and list it under
   "Phase 46 amendments" with the card (P46-1, -10, -11, -12).
5. **Keep every requirement that is true.** Rewording is not deleting. Do not renumber requirements
   unless the numbering is broken (duplicates, gaps); tests cite numbers, so list any renumbering.
6. Keep `**Version**` as is: the integrator bumps versions and the index.

## Rules

- Edit only your spec file. Do not run `git` commands that change state (no add, commit, stash,
  checkout, reset). Do not edit tests, code, `specs/README.md` or another spec.
- A requirement that has no test is kept if the code does it; list it under "Untested".
- A live probe runs in a throwaway home you create with `d=$(mktemp -d)` and delete with
  `rm -rf "$d"` — that one directory, never a glob (`/tmp/tmp.*` deletes other workers' homes).
  Never touch `~/.docket`. Run every probe with its cwd inside `"$d"` (`cd "$d"` first):
  `docket init` may provision the cwd as a workdir and `chmod 700` it.
- A probe never contacts a hosted service (no real provider URL, even with a fake key): use a
  local endpoint such as `http://127.0.0.1:9/v1`, or read the code.
- Run `bash scripts/validate-specs.sh` and
  `uv run python scripts/maint/lint_cli_invocations.py <your spec>` before returning; both must be
  clean for your file.
- Finish the work before you return. Your return is read as the final state of the file.

## Return (short; no logs)

- **File / lines before -> after.**
- **Version bump:** PATCH (wording, history, paths) or MAJOR (a requirement removed or changed
  meaning to match the code), with one line why.
- **Corrected claims:** `old line: what it said -> what the code does (evidence file:line)`.
- **Requirements deleted** (behaviour that does not exist) and **renumbered**, if any.
- **Phase 46 amendments:** requirement -> card.
- **Code defects** found, with evidence.
- **Untested** requirements (spot check).
- **Not verified:** anything you could not check.
