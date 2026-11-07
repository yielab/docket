#!/bin/sh
# The step's acceptance: the unit suite passes and the report format is the one finance signed off.
cd "$(dirname "$0")/.." || exit 2
PYTHONPATH=. python3 -m unittest discover -s tests || exit 1
PYTHONPATH=. python3 -c 'from report import format_total; assert format_total(1234567) == "$12345.67"'
