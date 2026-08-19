<#
.SYNOPSIS
    Manage a disposable, project-local PostgreSQL cluster.

.DESCRIPTION
    Creates and runs a PostgreSQL instance that belongs to THIS PROJECT ONLY, in
    .pgdata/, on a non-standard port (55432).

    Why not just use the PostgreSQL service already installed on the machine?

      * It needs no superuser password and no administrator rights.
      * It cannot damage, or be damaged by, any other database on the machine.
      * `reset` destroys and rebuilds it in seconds, which is what makes test runs
        reproducible: every run can start from a known-good state.
      * It mirrors what the Docker compose environment does in Phase 10, so the
        local and containerised paths behave the same way.

    The cluster listens on localhost only. Its superuser password is a local
    development value, not a secret.

.PARAMETER Action
    start   Create the cluster if needed, start it, and ensure roles/database exist
    stop    Stop the cluster (data is kept)
    status  Report whether the cluster is running
    reset   Stop, DELETE ALL DATA, and recreate from scratch
    psql    Open an interactive psql session as the application role

.EXAMPLE
    .\scripts\local_db.ps1 start
    .\scripts\local_db.ps1 reset
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "status", "reset", "psql")]
    [string]$Action = "start",

    [int]$Port = 55432,
    [string]$SuperPassword = "local-dev-superuser"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$dataDir = Join-Path $repoRoot ".pgdata"
$logFile = Join-Path $dataDir "server.log"

# --- locate the PostgreSQL binaries -----------------------------------------
function Get-PgBin {
    if ($env:PGBIN -and (Test-Path (Join-Path $env:PGBIN "pg_ctl.exe"))) { return $env:PGBIN }
    $candidates = Get-ChildItem "C:\Program Files\PostgreSQL" -Directory -ErrorAction SilentlyContinue |
        Sort-Object { [int]($_.Name -replace '\D', '0') } -Descending
    foreach ($c in $candidates) {
        $bin = Join-Path $c.FullName "bin"
        if (Test-Path (Join-Path $bin "pg_ctl.exe")) { return $bin }
    }
    throw "PostgreSQL binaries not found. Install PostgreSQL, or set `$env:PGBIN to the folder containing pg_ctl.exe."
}

$pgBin = Get-PgBin
$initdb = Join-Path $pgBin "initdb.exe"
$pgCtl = Join-Path $pgBin "pg_ctl.exe"
$psqlExe = Join-Path $pgBin "psql.exe"

# --- read credentials from .env so there is one source of truth --------------
function Get-EnvValue([string]$name, [string]$fallback) {
    $envPath = Join-Path $repoRoot ".env"
    if (Test-Path $envPath) {
        foreach ($line in Get-Content $envPath) {
            if ($line -match "^\s*$([regex]::Escape($name))\s*=\s*(.*)$") {
                $value = $Matches[1].Trim().Trim('"').Trim("'")
                if ($value) { return $value }
            }
        }
    }
    return $fallback
}

$dbName = Get-EnvValue "DB_NAME"          "claimdesk"
$appUser = Get-EnvValue "APP_DB_USER"      "claimdesk_app"
$appPassword = Get-EnvValue "APP_DB_PASSWORD"  "change-me-local-only"
$roUser = Get-EnvValue "DB_USER"          "claimdesk_qa_ro"
$roPassword = Get-EnvValue "DB_PASSWORD"      "change-me-local-only"

function Test-Running {
    & $pgCtl -D $dataDir status *> $null
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Superuser([string]$sql, [string]$database = "postgres") {
    $env:PGPASSWORD = $SuperPassword
    try {
        & $psqlExe -h localhost -p $Port -U postgres -d $database -v ON_ERROR_STOP=1 -q -c $sql
        if ($LASTEXITCODE -ne 0) { throw "psql failed: $sql" }
    } finally {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }
}

function Initialize-Cluster {
    Write-Host "==> Creating a new cluster in .pgdata (this happens once)" -ForegroundColor Cyan
    New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
    $pwFile = Join-Path $env:TEMP "claimdesk-pgpw-$PID.txt"
    Set-Content -Path $pwFile -Value $SuperPassword -Encoding ascii -NoNewline
    try {
        & $initdb -D (Join-Path $dataDir "data") -U postgres --pwfile=$pwFile -E UTF8 --locale=C -A scram-sha-256 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "initdb failed" }
    } finally {
        Remove-Item $pwFile -Force -ErrorAction SilentlyContinue
    }
}

function Start-Cluster {
    if (-not (Test-Path (Join-Path $dataDir "data"))) { Initialize-Cluster }

    $script:dataDir = Join-Path $repoRoot ".pgdata\data"
    if (Test-Running) {
        Write-Host "==> Cluster already running on port $Port" -ForegroundColor Green
    } else {
        Write-Host "==> Starting PostgreSQL on port $Port" -ForegroundColor Cyan
        # Start-Process rather than the call operator: the server process inherits
        # the parent's stdout handle, so a piped `& pg_ctl ... start` never returns
        # on Windows even after the server is up and serving. Redirecting to files
        # detaches the handles. `-w` makes pg_ctl wait for readiness, so the role
        # creation below cannot race the server.
        $outFile = Join-Path $env:TEMP "claimdesk-pgctl-$PID.out"
        $errFile = Join-Path $env:TEMP "claimdesk-pgctl-$PID.err"
        $proc = Start-Process -FilePath $pgCtl `
            -ArgumentList @("-D", $dataDir, "-l", $logFile, "-o", "-p $Port", "-w", "-t", "60", "start") `
            -Wait -PassThru -NoNewWindow -RedirectStandardOutput $outFile -RedirectStandardError $errFile
        Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
        if ($proc.ExitCode -ne 0) {
            Write-Host "Server log:" -ForegroundColor Red
            if (Test-Path $logFile) { Get-Content $logFile -Tail 20 }
            throw "pg_ctl start failed with exit code $($proc.ExitCode)"
        }
    }

    Write-Host "==> Ensuring database and roles exist (idempotent)" -ForegroundColor Cyan

    # The application role owns the schema. The QA role is granted SELECT and
    # nothing else, so a test can observe state but can never mutate it.
    # See docs/adr/0003-read-only-db-role.md
    Invoke-Superuser @"
DO `$`$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$appUser') THEN
        CREATE ROLE $appUser LOGIN PASSWORD '$appPassword';
    ELSE
        ALTER ROLE $appUser LOGIN PASSWORD '$appPassword';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$roUser') THEN
        CREATE ROLE $roUser LOGIN PASSWORD '$roPassword';
    ELSE
        ALTER ROLE $roUser LOGIN PASSWORD '$roPassword';
    END IF;
END
`$`$;
"@

    # CREATE DATABASE cannot run inside a DO block, so it needs an existence check.
    $env:PGPASSWORD = $SuperPassword
    try {
        $exists = & $psqlExe -h localhost -p $Port -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$dbName'"
    } finally {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }
    if ($exists -ne "1") {
        Invoke-Superuser "CREATE DATABASE $dbName OWNER $appUser"
    }

    # Grants are applied inside the target database, and DEFAULT PRIVILEGES cover
    # tables the application has not created yet - the application owns the schema
    # and creates its tables on first start.
    Invoke-Superuser @"
GRANT CONNECT ON DATABASE $dbName TO $roUser;
GRANT USAGE ON SCHEMA public TO $roUser;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO $roUser;
ALTER DEFAULT PRIVILEGES FOR ROLE $appUser IN SCHEMA public GRANT SELECT ON TABLES TO $roUser;
ALTER SCHEMA public OWNER TO $appUser;
"@ $dbName

    Write-Host ""
    Write-Host "Database ready:" -ForegroundColor Green
    Write-Host "  host=localhost port=$Port dbname=$dbName"
    Write-Host "  application role : $appUser (owner)"
    Write-Host "  QA role          : $roUser (SELECT only)"
    Write-Host ""
    Write-Host "Make sure .env contains:  DB_PORT=$Port"
}

switch ($Action) {
    "start" { Start-Cluster }

    "stop" {
        $script:dataDir = Join-Path $repoRoot ".pgdata\data"
        if (Test-Running) {
            Write-Host "==> Stopping cluster" -ForegroundColor Cyan
            & $pgCtl -D $dataDir -m fast -w stop | Out-Null
            Write-Host "Stopped." -ForegroundColor Green
        } else {
            Write-Host "Cluster is not running." -ForegroundColor Yellow
        }
    }

    "status" {
        $script:dataDir = Join-Path $repoRoot ".pgdata\data"
        if (Test-Running) {
            Write-Host "Running on port $Port" -ForegroundColor Green
        } else {
            Write-Host "Not running" -ForegroundColor Yellow
            exit 1
        }
    }

    "reset" {
        $script:dataDir = Join-Path $repoRoot ".pgdata\data"
        if (Test-Running) { & $pgCtl -D $dataDir -m immediate -w stop | Out-Null }
        Write-Host "==> Deleting .pgdata (all local test data will be lost)" -ForegroundColor Yellow
        Remove-Item -Recurse -Force (Join-Path $repoRoot ".pgdata") -ErrorAction SilentlyContinue
        Start-Cluster
    }

    "psql" {
        $env:PGPASSWORD = $appPassword
        try { & $psqlExe -h localhost -p $Port -U $appUser -d $dbName }
        finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
    }
}
