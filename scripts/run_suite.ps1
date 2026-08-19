<#
.SYNOPSIS
    Run the whole suite the way it is meant to be run: parallel, then serial.

.DESCRIPTION
    Two passes, because "run everything in parallel" is not a strategy, it is a
    hope:

      pass 1   pytest -m "not serial" -n <workers>
      pass 2   pytest -m serial                       (no xdist, one process)

    A test marked `serial` mutates state the whole suite shares - an
    application-wide setting, a seeded account other tests sign in as. Running it
    alongside anything else produces failures in *other* tests, which is the
    worst kind of flake to diagnose because the test that fails is not the test
    that is wrong.

    Right now **no test carries the marker**, and that is the intended outcome
    rather than an omission: every test creates its own uniquely-keyed data and
    asserts only on it. The pass exists anyway, because the moment somebody needs
    the marker they must not also have to invent the mechanism - that is when it
    gets skipped.

.PARAMETER Workers
    Passed to xdist. "auto" uses one process per core.

.PARAMETER Markers
    An extra marker expression, ANDed with the pass's own. For example
    -Markers smoke runs only the smoke tests, in both passes.

.PARAMETER Allure
    Also write Allure results, into allure-results/.

.EXAMPLE
    .\scripts\run_suite.ps1
    .\scripts\run_suite.ps1 -Workers 4 -Markers "api or db" -Allure
#>
[CmdletBinding()]
param(
    [string]$Workers = "auto",
    [string]$Markers = "",
    [switch]$Allure
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

# One run id for BOTH passes, so the two produce one artefact directory and one
# set of Allure results. Without this a serial failure would land in a different
# folder from the parallel run that preceded it.
if (-not $env:QA_RUN_ID) {
    $env:QA_RUN_ID = (Get-Date -Format "yyyyMMdd-HHmmss") + "-" + (Get-Random -Maximum 65535).ToString("x4")
}
Write-Host "==> Run id: $env:QA_RUN_ID" -ForegroundColor Cyan

$common = @("-q")
if ($Allure) { $common += "--alluredir=allure-results" }

function Invoke-Pass {
    param([string]$Name, [string]$Expression, [string[]]$Extra)

    $expr = if ($Markers) { "($Expression) and ($Markers)" } else { $Expression }
    Write-Host ""
    Write-Host "==> $Name  -m `"$expr`"" -ForegroundColor Cyan

    # `| Out-Host` is load-bearing. Without it pytest's stdout becomes part of
    # this function's RETURN VALUE - PowerShell functions return everything
    # written to the output stream, not just what `return` names - so the caller
    # received the whole test log where it expected an exit code, and a passing
    # suite was reported as failed.
    & $python -m pytest @common -m $expr @Extra | Out-Host
    $code = $LASTEXITCODE

    # Exit code 5 is "no tests were collected". For the serial pass that is the
    # NORMAL and desirable case - it means nothing in the suite has had to give
    # up on isolation. Treating it as a failure would make the correct state of
    # the world look like a broken build.
    if ($code -eq 5) {
        Write-Host "    (no tests matched - nothing to run in this pass)" -ForegroundColor DarkGray
        return 0
    }
    return $code
}

$parallel = Invoke-Pass -Name "Pass 1 of 2: parallel" -Expression "not serial" -Extra @("-n", $Workers)
$serial = Invoke-Pass -Name "Pass 2 of 2: serial" -Expression "serial" -Extra @("-p", "no:xdist")

Write-Host ""
if ($parallel -ne 0 -or $serial -ne 0) {
    Write-Host "Suite FAILED (parallel=$parallel serial=$serial)" -ForegroundColor Red
    exit 1
}
Write-Host "Suite passed (both passes)." -ForegroundColor Green
# Explicit, and not redundant. Without it the script exits with $LASTEXITCODE
# from the last pytest invocation - which for the serial pass is 5, "no tests
# collected". CI would then fail the build on a fully passing suite, and the
# console output would say it passed.
exit 0
