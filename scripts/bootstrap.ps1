<#
.SYNOPSIS
    One-command setup for a fresh clone on Windows.
.DESCRIPTION
    Creates the virtual environment, installs the framework in editable mode with
    developer tooling, and creates a .env from the template if one is missing.

    Deliberately idempotent: running it twice is safe, because "did I already run
    this?" is a question a new contributor should never have to answer.
.EXAMPLE
    .\scripts\bootstrap.ps1
#>
[CmdletBinding()]
param(
    [string]$PythonVersion = "3.11"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "==> Creating virtual environment (.venv) with Python $PythonVersion" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) {
    & py "-$PythonVersion" -m venv .venv
} else {
    Write-Host "    .venv already exists - reusing it"
}

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

Write-Host "==> Installing the framework in editable mode with dev tooling" -ForegroundColor Cyan
& $python -m pip install --upgrade pip --quiet
& $python -m pip install -e ".[dev]"

Write-Host "==> Configuring environment" -ForegroundColor Cyan
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "    Created .env from .env.example - review the values before running DB tests"
} else {
    Write-Host "    .env already exists - left untouched"
}

Write-Host "==> Verifying the installation" -ForegroundColor Cyan
& $python -m pytest -m framework -q

Write-Host ""
Write-Host "Setup complete. Next:" -ForegroundColor Green
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  .\scripts\quality.ps1        # lint + types + framework unit tests"
