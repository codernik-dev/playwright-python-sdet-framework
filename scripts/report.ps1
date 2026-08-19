<#
.SYNOPSIS
    Generate and open the Allure report for the most recent run.

.DESCRIPTION
    Allure results are raw JSON; a report is a static site generated from them.
    This script does the generation step, keeps report history so trends
    accumulate across runs, and opens the result.

    History is the part people skip, and it is the part that makes the report
    worth having. Without it every report is a snapshot that cannot answer "is
    this test newly broken, or has it been failing for a week?" - which is the
    first thing anyone wants to know about a red build.

.PARAMETER ResultsDir
    Where pytest wrote its raw results (pytest --alluredir=...).

.PARAMETER ReportDir
    Where the generated static site goes.

.PARAMETER Clean
    Discard accumulated history and start the trend from scratch.

.PARAMETER NoOpen
    Generate only. Used by CI, where nothing can open a browser.

.EXAMPLE
    pytest -q --alluredir=allure-results
    .\scripts\report.ps1
#>
[CmdletBinding()]
param(
    [string]$ResultsDir = "allure-results",
    [string]$ReportDir = "allure-report",
    [switch]$Clean,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Get-AllureCommand {
    $direct = Get-Command allure -ErrorAction SilentlyContinue
    if ($direct) { return @($direct.Source) }
    if (Get-Command npx -ErrorAction SilentlyContinue) { return @("npx", "--yes", "allure-commandline") }
    throw @"
The Allure command line tool was not found.

Allure renders the report; pytest only writes the raw results. Install it with
one of:

    npm install -g allure-commandline      (needs Node, which you have if npx works)
    scoop install allure
    https://github.com/allure-framework/allure2/releases

It needs a JVM. If `java -version` fails, install one first.
"@
}

if (-not (Test-Path $ResultsDir)) {
    throw "No results in '$ResultsDir'. Run the suite first: pytest -q --alluredir=$ResultsDir"
}

# @(...) around the call, not just inside the function. PowerShell unwraps a
# single-element array on return, so a one-element result came back as a bare
# string and `$allure[0]` indexed its first CHARACTER - the script then tried to
# run a command called "C". Forcing the array at the boundary is the only place
# the guarantee holds.
$allure = @(Get-AllureCommand)
$exe = $allure[0]
$prefix = @($allure | Select-Object -Skip 1)

# Carry the previous report's history into the new results BEFORE generating.
# Allure reads history from the results directory, not from the old report, so
# copying it the other way round (a common mistake) silently produces a report
# with an empty trend and no error to explain why.
$previousHistory = Join-Path $ReportDir "history"
if ($Clean) {
    Write-Host "==> Clean build: discarding previous history" -ForegroundColor Yellow
    Remove-Item -Recurse -Force $ReportDir -ErrorAction SilentlyContinue
} elseif (Test-Path $previousHistory) {
    Write-Host "==> Carrying history forward from the previous report" -ForegroundColor Cyan
    Copy-Item -Recurse -Force $previousHistory (Join-Path $ResultsDir "history")
}

Write-Host "==> Generating the report" -ForegroundColor Cyan
& $exe @prefix generate $ResultsDir --clean -o $ReportDir
if ($LASTEXITCODE -ne 0) { throw "allure generate failed with exit code $LASTEXITCODE" }

Write-Host ""
Write-Host "Report written to $ReportDir" -ForegroundColor Green

if (-not $NoOpen) {
    # `allure open` serves the report over HTTP. Opening index.html from the
    # filesystem does not work: the browser blocks the report's own data fetches
    # under the file:// origin policy and every widget renders empty.
    Write-Host "==> Serving the report (Ctrl+C to stop)" -ForegroundColor Cyan
    & $exe @prefix open $ReportDir
}
