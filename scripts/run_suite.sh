#!/usr/bin/env bash
# Run the whole suite in two passes - parallel, then serial. The Linux/CI
# counterpart of scripts/run_suite.ps1; see that file for why the second pass
# exists even though no test currently carries the `serial` marker.
#
#   ./scripts/run_suite.sh                       auto workers
#   WORKERS=4 ./scripts/run_suite.sh             fixed workers
#   MARKERS="api or db" ./scripts/run_suite.sh   narrow both passes
#   ALLURE=1 ./scripts/run_suite.sh              also write allure-results/
set -uo pipefail

cd "$(dirname "$0")/.."

WORKERS="${WORKERS:-auto}"
MARKERS="${MARKERS:-}"
ALLURE="${ALLURE:-0}"

# One run id for BOTH passes, so they share one artefact directory and one set
# of Allure results.
if [[ -z "${QA_RUN_ID:-}" ]]; then
  QA_RUN_ID="$(date -u +%Y%m%d-%H%M%S)-$(printf '%04x' $((RANDOM % 65536)))"
  export QA_RUN_ID
fi
echo "==> Run id: $QA_RUN_ID"

COMMON=(-q)
[[ "$ALLURE" == "1" ]] && COMMON+=(--alluredir=allure-results)

run_pass() {
  local name="$1" expression="$2"; shift 2
  local expr="$expression"
  [[ -n "$MARKERS" ]] && expr="($expression) and ($MARKERS)"

  echo
  echo "==> $name  -m \"$expr\""
  pytest "${COMMON[@]}" -m "$expr" "$@"
  local code=$?

  # Exit code 5 means nothing was collected. For the serial pass that is the
  # desirable outcome, not a failure: it means no test has had to give up on
  # isolation.
  if [[ $code -eq 5 ]]; then
    echo "    (no tests matched - nothing to run in this pass)"
    return 0
  fi
  return $code
}

run_pass "Pass 1 of 2: parallel" "not serial" -n "$WORKERS"
parallel=$?

run_pass "Pass 2 of 2: serial" "serial" -p no:xdist
serial=$?

echo
if [[ $parallel -ne 0 || $serial -ne 0 ]]; then
  echo "Suite FAILED (parallel=$parallel serial=$serial)"
  exit 1
fi
echo "Suite passed (both passes)."
# Explicit, for the same reason as the PowerShell version: without it the script
# would exit with the status of the last command, and the serial pass legitimately
# exits 5 ("no tests collected"). CI would fail a fully passing suite.
exit 0
