#!/usr/bin/env bash
# The local mirror of the CI quality gate (Linux / macOS / CI containers).
# Must stay identical in behaviour to scripts/quality.ps1 and to the PR workflow.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> ruff check"
ruff check .
echo "==> ruff format --check"
ruff format --check .
echo "==> mypy"
mypy
echo "==> framework unit tests"
pytest -m framework -q
echo
echo "Quality gate passed."
