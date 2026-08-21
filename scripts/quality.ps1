<#
.SYNOPSIS
    The local mirror of the CI quality gate.
.DESCRIPTION
    Runs exactly what the pull-request pipeline runs, in the same order, so a
    developer never discovers a lint failure only after pushing. Any deviation
    between this script and .github/workflows/tests.yml is a bug in one of them.
.PARAMETER Fix
    Apply safe automatic fixes and formatting instead of only reporting.
#>
[CmdletBinding()]
param([switch]$Fix)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

if ($Fix) {
    Write-Host "==> ruff check --fix" -ForegroundColor Cyan
    & $python -m ruff check . --fix
    Write-Host "==> ruff format" -ForegroundColor Cyan
    & $python -m ruff format .
} else {
    Write-Host "==> ruff check" -ForegroundColor Cyan
    & $python -m ruff check .
    if ($LASTEXITCODE -ne 0) { exit 1 }

    Write-Host "==> ruff format --check" -ForegroundColor Cyan
    & $python -m ruff format --check .
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

Write-Host "==> mypy" -ForegroundColor Cyan
& $python -m mypy
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "==> framework unit tests" -ForegroundColor Cyan
& $python -m pytest -m framework -q
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host ""
Write-Host "Quality gate passed." -ForegroundColor Green
