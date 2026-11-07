#!/bin/sh
# The step's acceptance: the unit suite must pass.
cd "$(dirname "$0")/.." || exit 2
PYTHONPATH=. python3 -m unittest discover -s tests
