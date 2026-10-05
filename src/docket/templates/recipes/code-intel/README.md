# code-intel

Two pod-scoped MCP servers that let an agent search code by syntax tree and ask a language
server about symbols. No roles, no pipeline, no members; `docket pod <p> apply code-intel`
installs the two server declarations for that pod only (the `mcp-server` items), and nothing
runs until a turn loads them. Applying never installs the binaries below.

| Server | Gives the agent | Declared | Needs on PATH |
| --- | --- | --- | --- |
| `ast-grep` | `find_code`, `find_code_by_rule`, `dump_syntax_tree`, `test_match_code_rule` | `access: read`; the server exposes exactly these four search tools and no write or rewrite tool | `uvx` and `ast-grep`; declared `isolate: false`, see below |
| `language-intel` | `definition`, `references`, `diagnostics`, `hover` | `access: read` with `tools:` restricted to those four, because the same server also offers `edit_file` and `rename_symbol`, which are never registered | `mcp-language-server` and `pyright-langserver` |

## Verified on 2026-10-04

- `ast-grep`: the ast-grep project's own server, https://github.com/ast-grep/ast-grep-mcp
  (README: `uvx --from git+https://github.com/ast-grep/ast-grep-mcp ast-grep-server`; its
  `main.py` registers exactly four `@mcp.tool()` functions, none writing). The `ast-grep`
  binary it shells out to is npm `@ast-grep/cli` 0.45.3 (`npm view` checked). The server is not
  on PyPI under that name, so it runs from the git URL; pin a commit there for reproducibility.
- `language-intel`: https://github.com/isaacphi/mcp-language-server (Go; install with
  `go install github.com/isaacphi/mcp-language-server@latest`; tool names read from its
  `tools.go`: `edit_file`, `definition`, `references`, `diagnostics`, `hover`,
  `rename_symbol`). The language server it drives is npm `pyright` 1.1.414, which ships the
  `pyright-langserver` binary (`npm view pyright bin` checked).

Neither server was executed here; the checks are package metadata and source reads.

## Isolation

A turn starts stdio servers in the same jail as `bash`. `ast-grep` declares `isolate: false`
because, measured 2026-10-05 through `system.bwrap_command_argv` with a warm cache, `uvx` fails
there with `Could not acquire lock ... Read-only file system (os error 30)` on its cache under
`~/.cache/uv`. Applying prints `ast-grep: runs unjailed (isolate: false)`; the server starts on the
host with your user's rights. `language-intel` stays jailed (its binary was not installed on the
measuring host); if it cannot start in the jail, add `isolate: false` to its document.

## Make it yours

`language-intel` is wired for Python. For another language change `--lsp` and its arguments
(the server's README lists gopls, rust-analyzer, typescript-language-server and clangd).
`--workspace .` resolves against the server process's working directory; set an absolute path if
the turn does not start in the codebase. Servers are stored pod-scoped in `config/mcp-servers.json`
and are selected like any other through the pod's `mcpServers` setting (global servers and this
pod's own).
