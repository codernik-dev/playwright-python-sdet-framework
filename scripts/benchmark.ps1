<#
.SYNOPSIS
    Measure serial versus parallel wall-clock, honestly.

.DESCRIPTION
    Produces the numbers that Phase 15 is allowed to publish. Everything about
    this script exists to stop it producing a flattering lie:

    * **Repetitions, and the median.** One before/after pair is not a
      measurement, it is an anecdote. The first run of anything is slower
      (cold caches, a cold connection pool, a browser binary read from disk for
      the first time), so a single "before" against a single "after" reliably
      overstates the improvement.
    * **A discarded warm-up run.** Measured and thrown away, for the same reason.
    * **Both directions in the same session, on the same machine, back to back.**
      Comparing today's parallel run against a serial number from a different
      machine is the most common way these figures become fiction.
    * **The machine is recorded.** A speed-up from parallelism is a statement
      about a core count. Without it the number means nothing.

    It does not compute a "% improvement" headline. The ratio is printed; what it
    is worth is a judgement for the person reading it, who can see the spread.

.PARAMETER Repetitions
    Measured runs per mode. Three is the minimum that lets you see a spread.

.PARAMETER Workers
    Worker count for the parallel mode.

.PARAMETER Markers
    Marker expression to benchmark. Defaults to the whole suite.

.EXAMPLE
    .\scripts\benchmark.ps1
    .\scripts\benchmark.ps1 -Repetitions 5 -Workers 4 -Markers "api or db"
#>
[CmdletBinding()]
param(
    [int]$Repetitions = 3,
    [string]$Workers = "auto",
    [string]$Markers = "not serial"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$cores = [Environment]::ProcessorCount
$cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
Write-Host "Machine : $cpu"
Write-Host "Cores   : $cores logical"
Write-Host "Markers : $Markers"
Write-Host "Repeats : $Repetitions measured runs per mode, after one discarded warm-up"
Write-Host ""

function Measure-Run {
    param([string[]]$Extra)

    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    $output = & $python -m pytest -q -m $Markers @Extra 2>&1
    $stopwatch.Stop()

    if ($LASTEXITCODE -ne 0) {
        $output | Select-Object -Last 15 | ForEach-Object { Write-Host $_ -ForegroundColor Red }
        throw "A benchmark run FAILED. A timing taken from a failing suite is meaningless - it may have exited early."
    }
    return $stopwatch.Elapsed.TotalSeconds
}

function Measure-Mode {
    param([string]$Name, [string[]]$Extra)

    Write-Host "==> $Name" -ForegroundColor Cyan
    Write-Host "    warm-up (discarded) ... " -NoNewline
    $warm = Measure-Run -Extra $Extra
    Write-Host ("{0:N2}s" -f $warm)

    $times = @()
    for ($i = 1; $i -le $Repetitions; $i++) {
        Write-Host "    run $i of $Repetitions ... " -NoNewline
        $elapsed = Measure-Run -Extra $Extra
        Write-Host ("{0:N2}s" -f $elapsed)
        $times += $elapsed
    }
    return , $times
}

$serialTimes = Measure-Mode -Name "serial (-p no:xdist)" -Extra @("-p", "no:xdist")
Write-Host ""
$parallelTimes = Measure-Mode -Name "parallel (-n $Workers)" -Extra @("-n", $Workers)

function Get-Median([double[]]$values) {
    $sorted = $values | Sort-Object
    $middle = [int][Math]::Floor($sorted.Count / 2)
    if ($sorted.Count % 2 -eq 1) { return $sorted[$middle] }
    return ($sorted[$middle - 1] + $sorted[$middle]) / 2
}

$serialMedian = Get-Median $serialTimes
$parallelMedian = Get-Median $parallelTimes

Write-Host ""
Write-Host "================ RESULT ================" -ForegroundColor Green
Write-Host ("serial   : median {0,6:N2}s   (min {1:N2}  max {2:N2})" -f $serialMedian, ($serialTimes | Measure-Object -Minimum).Minimum, ($serialTimes | Measure-Object -Maximum).Maximum)
Write-Host ("parallel : median {0,6:N2}s   (min {1:N2}  max {2:N2})" -f $parallelMedian, ($parallelTimes | Measure-Object -Minimum).Minimum, ($parallelTimes | Measure-Object -Maximum).Maximum)
Write-Host ("ratio    : {0:N2}x on {1} logical cores" -f ($serialMedian / $parallelMedian), $cores)
Write-Host ""
Write-Host "Quote these WITH the machine and the core count. A speed-up figure" -ForegroundColor DarkGray
Write-Host "without the hardware it was measured on is not a measurement." -ForegroundColor DarkGray
