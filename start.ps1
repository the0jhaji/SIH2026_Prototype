# start.ps1 — One-command startup for the Astra AI / SIH2026 prototype.
# Opens a terminal in the project root and run:  .\start.ps1
#
# Starts (in separate, independent PowerShell processes):
#   * FastAPI backend   -> http://127.0.0.1:8000  (dual YOLO object detection)
#   * React/Vite frontend-> http://127.0.0.1:5173 (proxies /api & /ws to :8000)
#
# Detection runs the general COCO ONNX and the custom experiment ONNX, merging
# them with cross-model NMS. Override the two independent slots with
# DETECTION_GENERAL_MODEL_PATH and DETECTION_CUSTOM_MODEL_PATH (paths are
# relative to models/ unless absolute). Activity perception (ACTIVITY_BACKEND=
# live) advances the experiment only when the required objects are visibly
# present on camera.
#
# Shutdown: press Ctrl+C in this window (or close it) and the child backend/
# frontend processes are terminated so nothing is left running.

[CmdletBinding()]
param(
    # When set, print status then cleanly stop the children and exit (test hook).
    [switch]$Test
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$BackendPy = Join-Path $Root 'backend\.venv\Scripts\python.exe'
$FrontendDir = Join-Path $Root 'frontend'
$LogDir = Join-Path $Root '.startup_logs'
$BackendLog = Join-Path $LogDir 'backend.log'
$FrontendLog = Join-Path $LogDir 'frontend.log'
$PidFile = Join-Path $LogDir 'child_pids.json'

$BackendPort = 8000
$FrontendPort = 5173
$BackendUrl = "http://127.0.0.1:$BackendPort"
$FrontendUrl = "http://127.0.0.1:$FrontendPort"

$childPids = [System.Collections.Generic.List[int]]::new()

function Write-Step([string]$msg) { Write-Host "[start.ps1] $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host "[start.ps1] $msg" -ForegroundColor Green }
function Write-Err([string]$msg)  { Write-Host "[start.ps1] $msg" -ForegroundColor Yellow }

function Get-PortOwner([int]$port) {
    try {
        $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $c) { return $c.OwningProcess }
    } catch { }
    return $null
}

function Test-PortOpen([int]$port) {
    return $null -ne (Get-PortOwner $port)
}

function Invoke-Get([string]$url, [int]$timeoutSec = 5) {
    try { return Invoke-RestMethod -Uri $url -TimeoutSec $timeoutSec } catch { return $null }
}

function Test-TcpOpen([int]$port) {
    # Port is "open" when any process is LISTENING on it (works for both
    # uvicorn and vite; Get-NetTCPConnection is reliable on Windows PS 5.1).
    return $null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Stop-Children {
    Write-Step "Shutting down child processes..."
    foreach ($pidVal in $script:childPids) {
        try { Stop-Process -Id $pidVal -Force -ErrorAction SilentlyContinue; Write-Ok "Stopped PID $pidVal" }
        catch { Write-Err "Could not stop PID $pidVal" }
    }
    # Also free the ports we own in case a child spawned grandchildren.
    foreach ($port in @($BackendPort, $FrontendPort)) {
        $owner = Get-PortOwner $port
        if ($null -ne $owner) { Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue }
    }
    $script:childPids.Clear()
    Remove-Item -LiteralPath $PidFile -ErrorAction SilentlyContinue
}

function Save-Pids {
    @{ backend = if ($backend) { $backend.Id } else { $null }; frontend = if ($frontend) { $frontend.Id } else { $null } } |
        ConvertTo-Json | Set-Content -LiteralPath $PidFile -Encoding utf8
}

# ---------------------------------------------------------------- preflight
Write-Step "Astra AI prototype startup"
Write-Step "Root: $Root"

if (-not (Test-Path -LiteralPath $BackendPy)) {
    Write-Err "Backend Python venv not found: $BackendPy"
    Write-Err "Create it first (see README.md / backend) and re-run .\start.ps1"
    exit 1
}
if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir 'node_modules'))) {
    Write-Err "Frontend node_modules not found: $(Join-Path $FrontendDir 'node_modules')"
    Write-Err "Run `npm install` in frontend/ first, then re-run .\start.ps1"
    exit 1
}

# Port availability checks give a clear message instead of a silent bind failure.
foreach ($p in @(@{n='backend';port=$BackendPort}, @{n='frontend';port=$FrontendPort})) {
    if (Test-PortOpen $p.port) {
        $owner = Get-PortOwner $p.port
        Write-Err "Port $($p.port) ($($p.n)) is already in use by PID $owner."
        Write-Err "Stop that process (or run .\stop.ps1 if it was started by this script) and re-run .\start.ps1"
        exit 1
    }
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Register cleanup so closing the window also stops the children. The action
# runs in a separate event runspace, so it reads the PID file instead of
# depending on script-scope functions/variables.
Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    $root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
    $pf = Join-Path $root '.startup_logs\child_pids.json'
    if (Test-Path -LiteralPath $pf) {
        $d = Get-Content -LiteralPath $pf -Raw | ConvertFrom-Json
        foreach ($p in @($d.backend, $d.frontend) | Where-Object { $_ }) {
            Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
        }
        foreach ($prt in 8000, 5173) {
            $c = Get-NetTCPConnection -LocalPort $prt -State Listen -ErrorAction SilentlyContinue
            if ($c) { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue }
        }
        Remove-Item -LiteralPath $pf -ErrorAction SilentlyContinue
    }
} | Out-Null

try {
    # ---------------------------------------------------------------- backend
    Write-Step "Starting FastAPI backend on port $BackendPort (detection: yolo)..."
    # Detection env. There are exactly TWO models and their roles are fixed:
    #
    #   GENERAL / PRIMARY  -> models/detection/yolov8n.onnx   (80 COCO classes)
    #                         person, bottle, cup, chair, laptop, cell phone,
    #                         book, keyboard, ... This is the only model that
    #                         may serve as the sole detector.
    #   SPECIALISED        -> models/detection/experiment_custom.onnx
    #                         (2 classes: red_box, yellow_box) ONLY. It cannot
    #                         see a person, so it must never replace the general
    #                         model. Used only via DETECTION_BACKEND=dual.
    #
    #   DETECTION_BACKEND=yolo  -> one primary model (default, ~2x faster)
    #   DETECTION_BACKEND=dual  -> general + custom, cross-model NMS (~2x cost)
    #   DETECTION_CONF_THRESHOLD=0.25 -> YOLOv8 default. Measured: 0.50 hides most
    #       real objects (15 dets/14 frames, person+laptop only); 0.25 gives 32
    #       across 5 classes. Do not raise this without measuring.
    #   DETECTION_CV_THREADS=8  -> OpenCV DNN thread pool. Measured 293ms/forward at
    #       8 threads vs 666ms at 1 thread on this 16-CPU host.
    #   DETECTION_FPS  -> AI rate cap, decoupled from the 30 FPS camera (newest frame wins)
    $env:CAMERA_MOCK = 'false'
    $env:DETECTION_ENABLED = 'true'
    $env:DETECTION_BACKEND = 'yolo'
    $env:DETECTION_MODEL_PATH = 'detection/yolov8n.onnx'
    $env:DETECTION_CONF_THRESHOLD = '0.25'
    $env:DETECTION_CV_THREADS = '8'
    $env:DETECTION_FPS = '8'
    $env:ACTIVITY_BACKEND = 'live'
    $backend = Start-Process -FilePath $BackendPy `
        -ArgumentList '-m','uvicorn','app.main:app','--host','0.0.0.0','--port',"$BackendPort" `
        -WorkingDirectory (Join-Path $Root 'backend') `
        -WindowStyle Hidden -RedirectStandardOutput $BackendLog -RedirectStandardError (Join-Path $LogDir 'backend.err.log') `
        -PassThru
    $childPids.Add($backend.Id)
    Write-Ok "Backend started (PID $($backend.Id))"

    # --------------------------------------------------------------- frontend
    Write-Step "Starting React/Vite frontend on port $FrontendPort..."
    $frontend = Start-Process -FilePath 'powershell.exe' `
        -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-Command','npm run dev' `
        -WorkingDirectory $FrontendDir `
        -WindowStyle Hidden -RedirectStandardOutput $FrontendLog -RedirectStandardError (Join-Path $LogDir 'frontend.err.log') `
        -PassThru
    $childPids.Add($frontend.Id)
    Write-Ok "Frontend started (PID $($frontend.Id))"

    Save-Pids

    # --------------------------------------------------------- health checks
    Write-Step "Waiting for services to become ready..."
    $backendReady = $false; $frontendReady = $false
    for ($i = 0; $i -lt 40; $i++) {
        if (-not $backendReady) {
            $h = Invoke-Get "$BackendUrl/api/health" 3
            if ($null -ne $h -and $h.status -eq 'ok') { $backendReady = $true }
        }
        if (-not $frontendReady) {
            # TCP probe: catches a listening vite server without relying on
            # parsing its HTML response (Invoke-RestMethod chokes on that).
            if (Test-TcpOpen $FrontendPort) { $frontendReady = $true }
        }
        if ($backendReady -and $frontendReady) { break }
        if (($i + 1) % 10 -eq 0) {
            $bs = if ($backendReady) { 'up' } else { 'down' }
            $fs = if ($frontendReady) { 'up' } else { 'down' }
            Write-Host "  ...waiting: backend=$bs frontend=$fs (${i}s)" -ForegroundColor DarkGray
        }
        Start-Sleep -Milliseconds 1000
    }

    # ------------------------------------------------------------- reporting
    if ($backendReady) {
        Write-Ok "Backend  UP   -> $BackendUrl   (GET /api/health => ok)"
        try {
            $det = $null
            for ($i = 0; $i -lt 20 -and $null -eq $det; $i++) { $det = Invoke-Get "$BackendUrl/api/detection/status" 3; Start-Sleep -Milliseconds 400 }
            # Print the model that is ACTUALLY loaded, not the one we requested.
            $cls = @()
            if ($det.classes) { $cls = $det.classes }
            $clsText = if ($cls.Count -le 12) { $cls -join ', ' } else { "$($cls[0..7] -join ', ') ... (+$($cls.Count - 8) more)" }
            $sizeText = if ($det.modelSizeMb) { "$($det.modelSizeMb) MB" } else { 'unknown' }
            $role = if ($det.generalPurpose -eq $false) {
                'SPECIALISED (narrow vocabulary - CANNOT detect person/bottle/cup!)'
            } else { 'GENERAL / PRIMARY' }
            Write-Host ""
            Write-Host "  [DETECTION RUNTIME]" -ForegroundColor Cyan
            Write-Host "    backend         = $($det.detector)"
            Write-Host "    model path      = $($det.modelPath)"
            Write-Host "    model size      = $sizeText"
            Write-Host "    model type      = ONNX (OpenCV DNN, CPU)"
            Write-Host "    role            = $role"
            Write-Host "    class count     = $($det.classCount)"
            Write-Host "    class names     = $clsText"
            Write-Host "    input size      = $($det.inputSize)"
            Write-Host "    conf threshold  = $($det.confThreshold)"
            Write-Host "    iou threshold   = $($det.iouThreshold)"
            Write-Host "    cv threads      = $env:DETECTION_CV_THREADS"
            Write-Host "    ai rate         = target $($det.targetFps) fps / actual $($det.actualFps) fps"
            Write-Host "    inference       = $($det.inferenceStatus) ($($det.inferenceMs)ms)"
            Write-Host "    objects         = $($det.detectionCount) stable / $($det.rawDetectionCount) raw"
            Write-Host "    trace logging   = $($det.traceEnabled)"
            if ($det.error) { Write-Host "    ERROR           = $($det.error)" -ForegroundColor Red }
            if ($det.generalPurpose -eq $false) {
                Write-Err "    ^ This model cannot detect a person. Set DETECTION_BACKEND=yolo for the general model."
            }
            Write-Host ""
        } catch { Write-Err "  detection status unavailable: $($_.Exception.Message)" }
    } else {
        Write-Err "Backend did not become ready on $BackendUrl within timeout."
        Write-Err "See $BackendLog"
    }

    if ($frontendReady) {
        Write-Ok "Frontend UP -> $FrontendUrl"
    } else {
        Write-Err "Frontend did not become ready on $FrontendUrl within timeout."
        Write-Err "See $FrontendLog"
    }

    Write-Host ""
    Write-Host "  Dashboard : $FrontendUrl   (proxies /api & /ws -> $BackendUrl)" -ForegroundColor Green
    Write-Host "  API       : $BackendUrl/docs" -ForegroundColor Green
    Write-Host "  Logs      : $LogDir" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Services are running in separate windows/processes." -ForegroundColor Cyan
    Write-Host "Press Ctrl+C here (or close this window) to stop both services." -ForegroundColor Cyan

    if ($Test) {
        Write-Host "[start.ps1] -Test: stopping children and exiting." -ForegroundColor Yellow
        return
    }

    # Keep this process alive so Ctrl+C / closure triggers cleanup.
    while ($true) { Start-Sleep -Seconds 3600 }
}
finally {
    Stop-Children
}
