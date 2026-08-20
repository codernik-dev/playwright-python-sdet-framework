#!/usr/bin/env bash
# Generate (and optionally open) the Allure report - the Linux/CI counterpart of
# scripts/report.ps1. Kept in step with it deliberately: a developer on Windows
# and a CI job on Linux must produce the same report from the same results, or
# the report stops being evidence and becomes a local artefact.
#
#   ./scripts/report.sh                       generate and serve
#   ./scripts/report.sh --no-open             generate only (CI)
#   ./scripts/report.sh --clean               discard the accumulated trend
set -euo pipefail

RESULTS_DIR="${RESULTS_DIR:-allure-results}"
REPORT_DIR="${REPORT_DIR:-allure-report}"
OPEN_REPORT=1
CLEAN=0

for arg in "$@"; do
  case "$arg" in
    --no-open) OPEN_REPORT=0 ;;
    --clean)   CLEAN=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")/.."

if [[ ! -d "$RESULTS_DIR" ]]; then
  echo "No results in '$RESULTS_DIR'. Run the suite first:" >&2
  echo "    pytest -q --alluredir=$RESULTS_DIR" >&2
  exit 1
fi

if command -v allure >/dev/null 2>&1; then
  ALLURE=(allure)
elif command -v npx >/dev/null 2>&1; then
  ALLURE=(npx --yes allure-commandline)
else
  cat >&2 <<'EOF'
The Allure command line tool was not found. pytest writes raw results; Allure
renders them. Install it with one of:

    npm install -g allure-commandline
    https://github.com/allure-framework/allure2/releases

It needs a JVM.
EOF
  exit 1
fi

# History lives in the RESULTS directory when generating, and is produced into
# the REPORT directory. Copying it the wrong way round yields an empty trend and
# no error - so it is done here, once, correctly.
if [[ "$CLEAN" -eq 1 ]]; then
  echo "==> Clean build: discarding previous history"
  rm -rf "$REPORT_DIR"
elif [[ -d "$REPORT_DIR/history" ]]; then
  echo "==> Carrying history forward from the previous report"
  cp -r "$REPORT_DIR/history" "$RESULTS_DIR/history"
fi

echo "==> Generating the report"
"${ALLURE[@]}" generate "$RESULTS_DIR" --clean -o "$REPORT_DIR"

echo "Report written to $REPORT_DIR"

if [[ "$OPEN_REPORT" -eq 1 ]]; then
  # `allure open` serves over HTTP. Opening index.html directly does not work:
  # the file:// origin policy blocks the report's own data fetches and every
  # widget renders empty.
  echo "==> Serving the report (Ctrl+C to stop)"
  "${ALLURE[@]}" open "$REPORT_DIR"
fi
