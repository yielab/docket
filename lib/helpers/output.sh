#!/usr/bin/env bash
# Output helpers - info, success, warn, error messages with colors

dbg()        { [[ "$DEBUG" == "1" ]] && echo -e "${DIM}[dbg] $*${RESET}" >&2 || true; }
info()       { echo -e "${ARROW} $*"; }
success()    { echo -e "${TICK} $*"; }
warn()       { echo -e "${WARN} $*"; }
error()      { echo -e "${CROSS} ${RED}Error:${RESET} $*" >&2; exit 1; }
fail()       { echo -e "${CROSS} $*" >&2; }        # print error without exiting
error_hint() {                                      # error with a hint line
  echo -e "${CROSS} ${RED}Error:${RESET} $1" >&2
  echo -e "  ${DIM}Hint: $2${RESET}" >&2
  exit 1
}
header()     { echo -e "\n${BOLD}$*${RESET}"; }
dim()        { echo -e "${DIM}$*${RESET}"; }
