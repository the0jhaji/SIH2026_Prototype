# stop.ps1 — Stop the backend/frontend processes started by start.ps1.
# Run from the project root:  .\stop.ps1
#
# Reads child PIDs recorded by start.ps1 (.startup_logs/child_pids.json),
# stops them, then frees the 8000/5173 ports belonging to those services.
# Safe to run even if the controller window is gone or services already exited.

$ErrorActionPreference = 'Continue'
$Root = $PSScriptRoot
$PidFile = Join-Path $Root '.startup_logs\child_pids.json'
$BackendPort = 8000
$FrontendPort = 5173

function Write-Step([string]$msg) { Write-Host "[stop.ps1] $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host "[stop.ps1] $msg" -ForegroundColor Green }
function Write-Err([string]$msg)  { Write-Host "[stop.ps1] $msg" -ForegroundColor Yellow }

function Get-PortOwner([int]$port) {
    try {
        $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $c) { return $c.OwningProcess }
    } catch { }
    return $null
}

$stopped = @()

# 1) Stop PIDs recorded by start.ps1.
if (Test-Path -LiteralPath $PidFile) {
    try {
        $data = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
        $pids = @($data.backend, $data.frontend) | Where-Object { $_ }
        foreach ($p in $pids) {
            if (Get-Process -Id $p -ErrorAction SilentlyContinue) {
                Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
                $stopped += $p
                Write-Ok "Stopped PID $p"
            }
        }
    } catch {
        Write-Err "Could not parse $PidFile : $($_.Exception.Message)"
    }
}

# 2) Free the ports (in case a child spawned grandchildren that bind them).
foreach ($port in @($BackendPort, $FrontendPort)) {
    $owner = Get-PortOwner $port
    if ($null -ne $owner) {
        Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
        Write-Ok "Freed port $port (PID $owner)"
    }
}

Remove-Item -LiteralPath $PidFile -ErrorAction SilentlyContinue

if ($stopped.Count -gt 0 -or $null -ne (Get-PortOwner $BackendPort) -or $null -ne (Get-PortOwner $FrontendPort)) {
    Start-Sleep -Seconds 1
    foreach ($port in @($BackendPort, $FrontendPort)) {
        if ($null -eq (Get-PortOwner $port)) { Write-Ok "Port $port is free." }
    }
} else {
    Write-Step "Nothing to stop (no running services from this repository)."
}
