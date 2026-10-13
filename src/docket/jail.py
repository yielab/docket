"""``python -m docket.jail``: confine this process with Landlock and seccomp, then exec a command.

Fails closed with exit 125 when the confinement cannot be enforced; runs nothing in that case."""

from __future__ import annotations

import argparse
import os
import sys

from docket.edges.adapters import landlock

EXIT_REFUSED = 125
EXIT_NOT_RUNNABLE = 127


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m docket.jail", add_help=True)
    parser.add_argument("--rw", action="append", default=[], help="read-write root")
    parser.add_argument("--ro", action="append", default=[], help="extra read-only root")
    parser.add_argument("--refuse", default="", help="refuse to run, printing this reason")
    parser.add_argument("--net", choices=("none", "open"), default="none")
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    return parser


def confine(rw: list[str], ro: list[str], network: bool) -> None:
    """Apply NO_NEW_PRIVS, the Landlock ruleset and, without network, the socket filter."""
    abi = landlock.abi_version()
    if abi < 1:
        raise landlock.LandlockError("Landlock is not available on this kernel")
    plan = landlock.plan_ruleset(
        abi,
        tuple(os.path.realpath(p) for p in rw),
        (*landlock.default_ro_roots(), *(os.path.realpath(p) for p in ro)),
        network,
    )
    program = None if network else landlock.socket_filter()
    if not network and program is None and abi < 4:
        raise landlock.LandlockError("network none cannot be enforced on this architecture")
    landlock.no_new_privs()
    if program is not None:
        landlock.install_socket_filter(program)
    landlock.enforce(plan)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    if not command:
        print("jail: no command given", file=sys.stderr)
        return EXIT_REFUSED
    if args.refuse:
        print(f"jail: refusing to run: {args.refuse}", file=sys.stderr)
        return EXIT_REFUSED
    try:
        confine(args.rw, args.ro, args.net == "open")
    except (landlock.LandlockError, OSError) as ex:
        print(f"jail: refusing to run unconfined: {ex}", file=sys.stderr)
        return EXIT_REFUSED
    try:
        os.execvp(command[0], command)
    except OSError as ex:
        print(f"jail: cannot run {command[0]}: {ex}", file=sys.stderr)
        return EXIT_NOT_RUNNABLE
    return EXIT_NOT_RUNNABLE


if __name__ == "__main__":
    sys.exit(main())
