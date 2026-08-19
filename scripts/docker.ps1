<#
.SYNOPSIS
    Run Docker commands against the engine inside WSL2, from PowerShell.

.DESCRIPTION
    This project uses Docker Engine installed inside WSL2 Ubuntu rather than
    Docker Desktop. That choice was made for concrete reasons:

      * it needs no administrator elevation to install;
      * it avoids Docker Desktop's licensing terms for larger organisations;
      * it is closer to what CI actually runs - a Linux daemon, not a VM shim.

    The cost is that `docker` is not on the Windows PATH. This script removes that
    friction: it translates the repository path to its /mnt/c form and runs the
    command inside WSL with the working directory already correct.

    If you later install Docker Desktop, this script becomes unnecessary - the
    `docker` command works natively - but it will keep working either way.

.EXAMPLE
    .\scripts\docker.ps1 version
    .\scripts\docker.ps1 compose up -d
    .\scripts\docker.ps1 compose run --rm tests pytest -m smoke
    .\scripts\docker.ps1 compose down -v
#>
# Deliberately NO param() block and NO [CmdletBinding()]. Any [Parameter()]
# attribute turns this into an advanced function, which adds PowerShell's common
# parameters - and then `-v` binds to -Verbose and `-w` is ambiguous with
# -WarningAction, so `docker.ps1 run -v /a:/b -w /b ...` fails before Docker ever
# sees it. Using the automatic $args variable passes every argument through
# untouched, which is the entire job of a wrapper.
$ErrorActionPreference = "Stop"
$DockerArgs = $args
$repoRoot = Split-Path -Parent $PSScriptRoot

function ConvertTo-WslPath([string]$windowsPath) {
    $resolved = (Resolve-Path $windowsPath).Path
    $drive = $resolved.Substring(0, 1).ToLower()
    $rest = $resolved.Substring(2) -replace '\\', '/'
    return "/mnt/$drive$rest"
}

$wslRepo = ConvertTo-WslPath $repoRoot

if (-not $DockerArgs -or $DockerArgs.Count -eq 0) {
    Write-Host "Docker engine runs inside WSL2. Usage:" -ForegroundColor Cyan
    Write-Host "  .\scripts\docker.ps1 version"
    Write-Host "  .\scripts\docker.ps1 compose up -d"
    Write-Host "  .\scripts\docker.ps1 compose logs -f app"
    Write-Host "  .\scripts\docker.ps1 compose down -v"
    exit 0
}

# Single-quote each argument for the bash -lc string, escaping any embedded
# quotes. Without this, an argument containing a space silently becomes two.
$escaped = $DockerArgs | ForEach-Object { "'" + ($_ -replace "'", "'\''") + "'" }
$command = "cd '$wslRepo' && docker " + ($escaped -join " ")

# The DEFAULT distribution, not a hard-coded `-d Ubuntu`. The original name was
# the one that happened to exist on the machine this was written on; the next
# machine installed `Ubuntu-24.04` and the wrapper failed with "no distribution"
# on a system where Docker was working perfectly. A script should not encode a
# local accident as a requirement.
& wsl -e bash -lc $command
exit $LASTEXITCODE
