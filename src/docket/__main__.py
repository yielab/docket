"""Entry point for `python -m docket`, the thin `bin/docket` launcher, and the installed
`docket` console script (`[project.scripts]` in pyproject.toml points at `main` below).
Importing this module has no side effect; `main()` only runs under
`if __name__ == "__main__":`."""

from __future__ import annotations

from docket import bootstrap as _bootstrap
from docket.hops.application import driver as _driver
from docket.interfaces.cli.app import app
from docket.kernel.home import current_home


def main() -> None:
    obj = _bootstrap.build_app(current_home())
    # A command can write trace records outside any turn (an answer's settlement); export them.
    _driver.start_export()
    app(obj=obj)


if __name__ == "__main__":
    main()
