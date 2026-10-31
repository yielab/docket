# docket-runtime API Reference

`docket-runtime` is the embeddable, policy-gated tool runtime shipped from the same source as
the `docket` CLI (see [packages/docket-runtime](https://github.com/yielab/docket/tree/main/packages/docket-runtime)).
It is a library a host application embeds, not a second CLI or a hosted service. Start from
[examples/runtime_embed.py](https://github.com/yielab/docket/blob/main/examples/runtime_embed.py);
[COMPATIBILITY.md](https://github.com/yielab/docket/blob/main/COMPATIBILITY.md) lists the adapter
configurations that are tested.

Only the names in `docket_runtime.__all__` are the supported public surface; everything else
(including the `docket_runtime._internal` tree a wheel build generates from `docket`'s own
`core`/`edges` modules) is private and may change without notice.

::: docket_runtime
    options:
      members:
        - Runtime
      show_root_heading: true
      show_source: true
      docstring_section_style: list

## Execution limits and results

::: docket_runtime._execution
    options:
      show_root_heading: true
      show_source: true
      docstring_section_style: list
