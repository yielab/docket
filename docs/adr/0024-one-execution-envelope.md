# ADR 0024 (D-60): one execution envelope, and a repository's commands need the operator's OK

**Question:** the Phase 40 audit left two structural gaps the cards could not close: (1) the
sandbox covers only the agent's `bash`, while `verifyCmd`, `run:` steps and `isolate: false` MCP
servers run on the host, so code the agent writes (a test file) executes with the operator's
rights even with the sandbox on, and the jail itself lets the agent read the whole disk and reach
the network; (2) a cloned repository's `.docket/` is applied by `docket init` with no confirmation
(D-59). The maintainer asked, on 2026-10-12, for the architecture to be rethought: what is
required, what is configurable, what is a first-install dependency on Linux, macOS and Windows,
and how other tools (Claude Code, Codex CLI, OpenHands) do it, without over-engineering.

**Where decided:** 2026-10-12, by the maintainer, over one session (research and drafts in the
gitignored `internal-docs/execution-envelope-design-2026-10-12.md`,
`internal-docs/sandbox-worktree-architecture-2026-10-12.md` and
`internal-docs/d-59-config-trust-research.md`).

**Decision:**

1. **Two layers, not three.** The *gate* (`core/tools.py`, `classify_command`, policies) decides
   whether a command may be asked for; always on, no dependency, no off switch. The *envelope*
   (the sandbox) is one jail where everything the project runs executes: the agent's `bash`,
   `verifyCmd`, `run:` steps and stdio MCP servers. The host runs only docket. The task worktree
   is the envelope's writable root and the unit of change; it is never a security boundary on
   its own.

2. **One permission rule for commands.** Inside the envelope every command is allowed except a
   high-risk class (prod deploy, money, secret access), which asks as today. Outside the envelope
   (sandbox off) the curated allowlist plus a pod's `allowCommands` applies, as today. Policies
   apply in both cases; a repository's policies can only add restrictions.

3. **Backends: Landlock + seccomp on Linux, Seatbelt on macOS, Docker when chosen.** Landlock
   (kernel >= 5.13; three syscalls through `ctypes`; unprivileged; no user namespace; inherited
   by children; irrevocable) makes the Linux envelope dependency-free and denies the home
   outright, which the bwrap profile (`--ro-bind / /`) never did; network is Landlock's TCP rules
   where the kernel has them (>= 6.7) and a seccomp filter denying `socket(AF_INET/AF_INET6)`
   everywhere. macOS uses `sandbox-exec` (Seatbelt), which ships with the OS, as Claude Code and
   Codex do. Docker stays as a backend the operator selects (`docket setup sandbox backend
   docker`), never a silent fallback. **bwrap is deleted.** Windows: WSL2 takes the Linux path;
   native Windows runs with the sandbox off and says so (no AppContainer work).

4. **Nothing is a package dependency.** A pip wheel cannot install a system package, and a hard
   requirement for a feature that is off by default is incoherent and would break `docket exec`
   in CI containers. `docket setup` and `install.sh` probe and print what is missing (a kernel
   without Landlock; nothing on macOS); the Homebrew formula declares nothing extra;
   `docket setup sandbox on` is the one point where a backend becomes required, and it fails
   closed naming the fix. Never a silent unsandboxed fallback (Claude Code's default; Codex and
   docket fail closed).

5. **Defaults, by the maintainer:** the sandbox stays **off by default** (D-56 stands; the
   probe result is printed at the end of `init`, at the top of `status` and in `doctor`);
   network inside the envelope is **`none`** by default, `open` is an operator grant a pod can
   only narrow, and the operator warms caches (`uv sync`, `npm ci`) before dispatch;
   **`isolate: false` on MCP servers is deleted** (it existed because `uv`'s cache was read-only
   in the jail; the envelope gives each pod a cache directory and sets `HOME` and the cache
   variables to it). A domain-allowlist egress proxy is deferred with a trigger: a real pod that
   needs one registry but not the internet.

6. **D-59, answered: a repository's commands need the operator's OK, remembered until they
   change.** `init` groups what `.docket/` brings into "adds to the team" (applies freely) and
   "runs on this machine" (pipeline `run:` steps, verify commands, MCP server commands, plugins,
   `allowCommands`, `network: open`, a role overlay that removes a built-in denial). The second
   group asks once on a terminal and is remembered in the operator's home
   (`~/.docket/reviewed-repos.json`, 0600, keyed by repository root and a digest of exactly those
   items); without a terminal nothing is created, exit 2 names the items and the review code, and
   `--accept <code>` allows exactly that version (a changed repository stops the script again
   without printing the new code). A shell, `sudo`, `ssh`, `nc` or `socat` in a repository's
   `allowCommands` is refused; the operator's own `pod set` is not. Shipped recipes by name are
   exempt; a recipe given as a directory is not. `docket run` picks the repository's changes up:
   text-only changes apply with one printed line, a changed command asks on a terminal (and runs
   the allowed version on `n`) or runs the allowed version with a warning off one. `docket pod
   apply` is renamed `docket pod update` (D-57: no alias). ADR 0012's live-path rule holds:
   dispatch and `docket start` never re-read `.docket/`; only a typed command does. This narrows
   ADR 0012's "operator command or nothing" to "operator command, by an operator who saw what
   runs".

7. **Not configurable, on purpose:** per-command sandbox profiles, custom seccomp or Landlock
   rules, which tools are jailed (all or nothing), and approving a repository's commands from a
   repository file or an environment variable.

**Consequences:** Phase 41 (TODO.md) ships the envelope in eight cards over four sub-waves
split by contention on `edges/adapters/system.py`; Phase 40's P40-5 and P40-13 ship the D-59
flow first. `README.md`, `docs/SECURITY-SIMPLE.md` and the quick start keep describing the
current behaviour until each card merges (D-37), and the integrator rewrites the affected
sentences in the same commit. The residual risks are stated rather than hidden: a shared kernel,
docket itself running as the user, merged code still needing human review, and `sandbox-exec`'s
deprecated status on macOS (shared with Claude Code and Codex). A release gate (P41-8) runs an
escape matrix on real backends so the envelope's claims are measured, not read.

**Closed by Waves 100–103 (2026-10-12/13).** All eight cards shipped. Two findings the decisions
above did not foresee: Landlock has no read-only sub-path, so the jail grants a repository's
`objects`, `refs` and `logs` (and a linked worktree's own git dir) instead of the git dir, and
refuses a root that holds a `.git` directory (use a worktree, or choose docker); and host-side
git in a task worktree names the git dirs docket recorded instead of reading the agent-writable
`.git` file. Seatbelt is pinned by unit tests and runs live only in the macOS CI job.
