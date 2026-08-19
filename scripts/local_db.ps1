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

# Two paths, two names, each meaning exactly one thing for the whole script.
#
#   clusterRoot  .pgdata        the project-local folder; holds the server log
#   dataDir      .pgdata\data   the PGDATA directory pg_ctl is pointed at
#
# They used to be one variable that was reassigned from inside the switch
# branches, and `reset` was silently broken as a result: after the folder was
# deleted, the existence check looked for `.pgdata\data\data`, did not find it,
# and initdb created the cluster one level too deep. The start that followed then
# reported `directory ... is not a database cluster directory` about a directory
# the same script had just created. A variable that means different things at
# different moments is not a shortcut, it is a bug waiting for the one code path
# nobody exercises often.
$clusterRoot = Join-Path $repoRoot ".pgdata"
$dataDir = Join-Path $clusterRoot "data"
$logFile = Join-Path $clusterRoot "server.log"

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
$pgIsReady = Join-Path $pgBin "pg_isready.exe"

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

function Wait-Accepting([int]$TimeoutSeconds = 60) {
    # Poll until the server ACCEPTS CONNECTIONS, which is not the same thing as
    # "the process exists": postmaster.pid appears well before recovery finishes.
    # Same principle as the framework's readiness fixture - poll for the condition
    # you actually depend on, with a deadline, instead of sleeping and hoping.
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $pgIsReady) {
            & $pgIsReady -h localhost -p $Port -q *> $null
            if ($LASTEXITCODE -eq 0) { return $true }
        } else {
            $client = [System.Net.Sockets.TcpClient]::new()
            try {
                $client.Connect("127.0.0.1", $Port)
                if ($client.Connected) { return $true }
            } catch {
                # not up yet - keep polling until the deadline
            } finally {
                $client.Dispose()
            }
        }
        Start-Sleep -Milliseconds 250
    }
    return $false
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
    New-Item -ItemType Directory -Path $clusterRoot -Force | Out-Null
    $pwFile = Join-Path $env:TEMP "claimdesk-pgpw-$PID.txt"
    Set-Content -Path $pwFile -Value $SuperPassword -Encoding ascii -NoNewline
    try {
        # initdb's own stderr is the only explanation available when it fails, so
        # it is captured and printed rather than discarded into Out-Null. The
        # first run on this machine failed with "postgres.bki does not exist" -
        # a message that names the problem exactly, and that the original
        # `| Out-Null` threw away, leaving only "initdb failed".
        $output = & $initdb -D $dataDir -U postgres --pwfile=$pwFile -E UTF8 --locale=C -A scram-sha-256 2>&1
        if ($LASTEXITCODE -ne 0) {
            $output | ForEach-Object { Write-Host $_ -ForegroundColor Red }
            throw "initdb failed"
        }
    } finally {
        Remove-Item $pwFile -Force -ErrorAction SilentlyContinue
    }
}

function Set-ClusterPort {
    # The port lives in the cluster's own postgresql.conf rather than being passed
    # on the command line with `-o "-p $Port"`.
    #
    # That is not a style preference. PowerShell 7's Start-Process does NOT quote
    # an ArgumentList element containing a space (Windows PowerShell 5.1 did), so
    # `-o "-p 55432"` arrived at pg_ctl as three separate arguments and it failed
    # with `unrecognized operation mode "55432"`. A cluster that knows its own port
    # removes the quoting question entirely, and `pg_ctl stop`/`status` then agree
    # with `start` without anyone having to pass the port again.
    $conf = Join-Path $dataDir "postgresql.conf"
    if (-not (Test-Path $conf)) { return }
    $marker = "# --- managed by scripts/local_db.ps1 ---"
    $lines = @(Get-Content $conf | Where-Object { $_ -ne $marker -and $_ -notmatch '^\s*port\s*=' })
    $lines += $marker
    $lines += "port = $Port"
    Set-Content -Path $conf -Value $lines -Encoding ascii
}

function Start-Cluster {
    if (-not (Test-Path (Join-Path $dataDir "PG_VERSION"))) { Initialize-Cluster }
    Set-ClusterPort

    if (Test-Running) {
        Write-Host "==> Cluster already running on port $Port" -ForegroundColor Green
    } else {
        Write-Host "==> Starting PostgreSQL on port $Port" -ForegroundColor Cyan
        # Started WITHOUT -Wait, and readiness is then polled below.
        #
        # `-Wait` looks like the obvious choice and it hangs forever. The server
        # pg_ctl launches inherits the redirected stdout/stderr handles, so
        # PowerShell's -Wait is waiting for the SERVER to exit, not for pg_ctl -
        # and the server is not supposed to exit. Redirecting to files does not
        # help, because the handles are still inherited. The result is a start
        # command that never returns even though the database is up and serving,
        # which is the most confusing possible failure: everything works and
        # nothing continues.
        $outFile = Join-Path $env:TEMP "claimdesk-pgctl-$PID.out"
        $errFile = Join-Path $env:TEMP "claimdesk-pgctl-$PID.err"
        Start-Process -FilePath $pgCtl `
            -ArgumentList @("-D", $dataDir, "-l", $logFile, "start") `
            -PassThru -NoNewWindow -RedirectStandardOutput $outFile -RedirectStandardError $errFile | Out-Null

        if (-not (Wait-Accepting 60)) {
            # Print pg_ctl's own message as well as the server log. A failed start
            # can leave the server log EMPTY - the server never got far enough to
            # write one - so a diagnostic that reads only the log says nothing at
            # exactly the moment it is needed.
            $startupError = (Get-Content $errFile -ErrorAction SilentlyContinue) -join "`n"
            if ($startupError) { Write-Host $startupError -ForegroundColor Red }
            Write-Host "Server log:" -ForegroundColor Red
            if (Test-Path $logFile) { Get-Content $logFile -Tail 20 }
            Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
            throw "PostgreSQL did not start accepting connections on port $Port within 60s."
        }
        Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
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
        if (Test-Running) {
            Write-Host "==> Stopping cluster" -ForegroundColor Cyan
            & $pgCtl -D $dataDir -m fast -w stop | Out-Null
            Write-Host "Stopped." -ForegroundColor Green
        } else {
            Write-Host "Cluster is not running." -ForegroundColor Yellow
        }
    }

    "status" {
        if (Test-Running) {
            Write-Host "Running on port $Port" -ForegroundColor Green
        } else {
            Write-Host "Not running" -ForegroundColor Yellow
            exit 1
        }
    }

    "reset" {
        if (Test-Running) { & $pgCtl -D $dataDir -m immediate -w stop | Out-Null }
        Write-Host "==> Deleting .pgdata (all local test data will be lost)" -ForegroundColor Yellow
        Remove-Item -Recurse -Force $clusterRoot -ErrorAction SilentlyContinue
        Start-Cluster
    }

    "psql" {
        $env:PGPASSWORD = $appPassword
        try { & $psqlExe -h localhost -p $Port -U $appUser -d $dbName }
        finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
    }
}
