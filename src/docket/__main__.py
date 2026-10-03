"""Entry point for `python -m docket`, the thin `bin/docket` launcher, and the installed
`docket` console script (`[project.scripts]` in pyproject.toml points at `main` below).
Importing this module has no side effect; `main()` only runs under
`if __name__ == "__main__":`."""

from __future__ import annotations

from docket.cli import app


def main() -> None:
    app()


if __name__ == "__main__":
    main()
