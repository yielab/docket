# Docket ten-minute starter

This copied-outside-checkout starter proves one governed file change using an exact locally built
root Docket artifact. It needs Python 3.11 and `uv`; it needs no API key, hosted model, Docker, or
`docket-runtime` package. The model is a deterministic loopback fake created by the starter.

## 1. Build and copy

From a Docket source checkout, build the root wheel and sdist once and copy this directory somewhere
outside the checkout:

```bash
uv build --out-dir /tmp/docket-starter-artifacts
cp -R examples/starter /tmp/docket-starter
cd /tmp/docket-starter
```

The artifact names contain the normalized package version. Select the one wheel that was just
built, then install its exact locked dependencies and the wheel itself:

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python --requirement requirements.lock
DOCKET_WHEEL=$(find /tmp/docket-starter-artifacts -maxdepth 1 -name 'docket-*.whl' -print -quit)
uv pip install --python .venv/bin/python --no-deps "$DOCKET_WHEEL"
```

Package downloads happen only during that installation. The run itself is local and credential
free. Prepare the two input files whose bytes the example protects:

```bash
mkdir -p workspace
printf '# Docket starter workspace\n' > workspace/README.md
printf 'starter pending\n' > workspace/starter-output.txt
export DOCKET_HOME="$PWD/.docket"
unset DOCKET_LLM_API_KEY DOCKET_LLM_BASE_URL OPENAI_API_KEY ANTHROPIC_API_KEY
export UV_OFFLINE=1 PIP_NO_INDEX=1
```

## 2. Run one command

Activate the environment so the documented command resolves the exact installed interpreter:

```bash
. .venv/bin/activate
python starter.py --workspace ./workspace
```

The command pauses twice. Enter `deny` at the first prompt; the target stays byte-for-byte
unchanged and the first task becomes `approval_denied`. Enter `grant` at the second prompt; Docket
resumes at the gated Implementer hop and its governed `write` tool changes only
`starter-output.txt` to `docket starter approved` followed by one LF.

The final output includes the exact target, task-list, trace, and audit paths. It also prints the
installed public inspection commands it ran:

```text
docket runs list --project docket-starter --json
docket runs show <run-id> --json
docket trace export docket-starter
docket audit verify
```

The persisted final hop contains a typed handoff. The run registry, trace export, and audit verifier
above belong to the root `docket` CLI; this starter does not install or make claims about the
separate `docket-runtime` facade.

## Troubleshooting

If the command says the `docket` executable is missing, repeat the exact-wheel installation step
with the same `.venv/bin/python`. Expected prerequisite errors are printed as `STARTER FAIL` without
a traceback. The supported acceptance path is Python 3.11 on Linux; port 8081 is never used.
